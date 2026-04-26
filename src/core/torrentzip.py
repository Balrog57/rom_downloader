import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from .dat_parser import normalize_checksum
from .signatures import hash_file_signatures, iter_archive_member_signatures
from .scanner import build_dat_md5_lookup


def find_7z_executable() -> str:
    """Retourne le chemin de 7-Zip si disponible."""
    env_path = os.environ.get('SEVENZIP_EXE') or os.environ.get('SEVEN_ZIP_EXE') or os.environ.get('Z7_EXE')
    candidates = [
        env_path,
        shutil.which('7z'),
        shutil.which('7za'),
        r'C:\Program Files\7-Zip\7z.exe',
        r'C:\Program Files (x86)\7-Zip\7z.exe',
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ''


def patch_zip_to_torrentzip(zip_path: Path) -> str:
    """Applique les champs TorrentZip/RomVault sur un ZIP existant."""
    data = bytearray(zip_path.read_bytes())
    min_pos = max(0, len(data) - 65557)
    eocd = -1
    for pos in range(len(data) - 22, min_pos - 1, -1):
        if data[pos:pos + 4] == b'PK\x05\x06':
            eocd = pos
            break
    if eocd < 0:
        raise RuntimeError("EOCD ZIP introuvable")

    cd_size = struct.unpack_from('<I', data, eocd + 12)[0]
    cd_offset = struct.unpack_from('<I', data, eocd + 16)[0]
    torrent_flag = 2
    torrent_time = (23 << 11) | (32 << 5)
    torrent_date = ((1996 - 1980) << 9) | (12 << 5) | 24

    ptr = 0
    while ptr < cd_offset:
        if data[ptr:ptr + 4] != b'PK\x03\x04':
            break
        struct.pack_into('<H', data, ptr + 6, torrent_flag)
        struct.pack_into('<H', data, ptr + 10, torrent_time)
        struct.pack_into('<H', data, ptr + 12, torrent_date)
        compressed_size = struct.unpack_from('<I', data, ptr + 18)[0]
        filename_length = struct.unpack_from('<H', data, ptr + 26)[0]
        extra_length = struct.unpack_from('<H', data, ptr + 28)[0]
        ptr += 30 + filename_length + extra_length + compressed_size

    ptr = cd_offset
    cd_end = cd_offset + cd_size
    while ptr < cd_end:
        if data[ptr:ptr + 4] != b'PK\x01\x02':
            break
        struct.pack_into('<H', data, ptr + 4, 0)
        struct.pack_into('<H', data, ptr + 8, torrent_flag)
        struct.pack_into('<H', data, ptr + 12, torrent_time)
        struct.pack_into('<H', data, ptr + 14, torrent_date)
        filename_length = struct.unpack_from('<H', data, ptr + 28)[0]
        extra_length = struct.unpack_from('<H', data, ptr + 30)[0]
        comment_length = struct.unpack_from('<H', data, ptr + 32)[0]
        ptr += 46 + filename_length + extra_length + comment_length

    central_directory = bytes(data[cd_offset:cd_offset + cd_size])
    crc_hex = f"{zlib.crc32(central_directory) & 0xffffffff:08X}"
    comment = f"TORRENTZIPPED-{crc_hex}".encode('ascii')
    struct.pack_into('<H', data, eocd + 20, len(comment))
    patched = bytes(data[:eocd + 22]) + comment
    zip_path.write_bytes(patched)
    return comment.decode('ascii')


def zip_is_torrentzip_compatible(zip_path: Path) -> bool:
    """Verifie les champs TorrentZip que RomVault produit."""
    try:
        data = zip_path.read_bytes()
        eocd = data.rfind(b'PK\x05\x06', max(0, len(data) - 65557))
        if eocd < 0:
            return False
        cd_size = struct.unpack_from('<I', data, eocd + 12)[0]
        cd_offset = struct.unpack_from('<I', data, eocd + 16)[0]
        comment_length = struct.unpack_from('<H', data, eocd + 20)[0]
        comment = data[eocd + 22:eocd + 22 + comment_length].decode('ascii', 'ignore')
        expected = f"TORRENTZIPPED-{zlib.crc32(data[cd_offset:cd_offset + cd_size]) & 0xffffffff:08X}"
        if comment != expected:
            return False

        ptr = cd_offset
        cd_end = cd_offset + cd_size
        while ptr < cd_end:
            if data[ptr:ptr + 4] != b'PK\x01\x02':
                return False
            version_made = struct.unpack_from('<H', data, ptr + 4)[0]
            flag = struct.unpack_from('<H', data, ptr + 8)[0]
            dos_time = struct.unpack_from('<H', data, ptr + 12)[0]
            dos_date = struct.unpack_from('<H', data, ptr + 14)[0]
            if version_made != 0 or flag != 2 or dos_time != 0xbc00 or dos_date != 0x2198:
                return False
            filename_length = struct.unpack_from('<H', data, ptr + 28)[0]
            extra_length = struct.unpack_from('<H', data, ptr + 30)[0]
            entry_comment_length = struct.unpack_from('<H', data, ptr + 32)[0]
            ptr += 46 + filename_length + extra_length + entry_comment_length
        return True
    except Exception:
        return False


def create_torrentzip_single_file(source_file: Path, internal_name: str, output_zip: Path) -> str:
    """Cree un ZIP Deflate maximal puis applique le header TorrentZip/RomVault."""
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = output_zip.with_name(f"{output_zip.stem}.tmp_torrentzip{output_zip.suffix}")
    if temp_zip.exists():
        temp_zip.unlink()

    seven_zip = find_7z_executable()
    with tempfile.TemporaryDirectory(prefix='rom_downloader_torrentzip_') as temp_dir:
        stage_dir = Path(temp_dir)
        staged_file = stage_dir / Path(internal_name).name
        shutil.copyfile(source_file, staged_file)

        if seven_zip:
            args = [
                seven_zip, 'a', '-tzip', '-mm=Deflate', '-mx=9', '-mfb=258',
                '-mpass=15', '-mmt=1', '-mtm=off', '-mtc=off', '-mta=off',
                str(temp_zip), staged_file.name
            ]
            result = subprocess.run(args, cwd=str(stage_dir), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or '7-Zip a echoue').strip())
        else:
            import zipfile
            with zipfile.ZipFile(temp_zip, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                zf.write(staged_file, arcname=staged_file.name)

    comment = patch_zip_to_torrentzip(temp_zip)
    os.replace(temp_zip, output_zip)
    return comment


def extract_archive_member_to_file(archive_path: Path, member_name: str, output_file: Path):
    """Extrait une entree precise d'une archive supportee vers un fichier."""
    from .dependencies import import_optional_package
    suffix = archive_path.suffix.lower()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if suffix == '.zip':
        import zipfile
        with zipfile.ZipFile(archive_path, 'r') as zf:
            with zf.open(member_name, 'r') as src, open(output_file, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        return

    if suffix == '.rar':
        rarfile = import_optional_package('rarfile', auto_install=True)
        if rarfile is None:
            raise RuntimeError("rarfile indisponible")
        with rarfile.RarFile(archive_path, 'r') as archive:
            with archive.open(member_name, 'r') as src, open(output_file, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        return

    if suffix == '.7z':
        py7zr = import_optional_package('py7zr', auto_install=True)
        if py7zr is None:
            raise RuntimeError("py7zr indisponible")
        with tempfile.TemporaryDirectory(prefix='rom_downloader_7z_extract_') as temp_dir:
            with py7zr.SevenZipFile(archive_path, mode='r') as archive:
                archive.extractall(path=temp_dir)
            extracted = Path(temp_dir) / member_name
            if not extracted.exists():
                matches = [item for item in Path(temp_dir).rglob('*') if item.is_file() and item.name == Path(member_name).name]
                extracted = matches[0] if matches else extracted
            if not extracted.exists():
                raise RuntimeError(f"entree 7z introuvable: {member_name}")
            shutil.copyfile(extracted, output_file)
        return

    raise RuntimeError(f"archive {suffix} non supportee")


def repack_verified_archives_to_torrentzip(dat_games: dict, rom_folder: str, dry_run: bool = False,
                                           log_func=print, status_callback=None,
                                           is_running=lambda: True) -> dict:
    """Recompresse les archives contenant des ROMs du DAT en ZIP TorrentZip/RomVault."""
    from ._facade import verify_downloaded_md5
    root = Path(rom_folder)
    summary = {'repacked': 0, 'skipped': 0, 'failed': 0, 'deleted': 0, 'items': []}
    if not root.exists():
        return summary

    md5_lookup = build_dat_md5_lookup(dat_games)
    if not md5_lookup:
        log_func("Nettoyage TorrentZip ignore: aucun MD5 dans le DAT")
        return summary

    archive_paths = [
        path for path in root.rglob('*')
        if path.is_file()
        and path.suffix.lower() in {'.zip', '.7z', '.rar'}
        and 'ToSort' not in path.parts
    ]

    total = len(archive_paths)
    log_func(f"Nettoyage TorrentZip: {total} archive(s) a verifier")

    for index, archive_path in enumerate(archive_paths, 1):
        if not is_running():
            log_func("Nettoyage TorrentZip arrete par l'utilisateur.")
            break
        if status_callback:
            status_callback(f"Nettoyage ZIP {index}/{total}: {archive_path.name[:60]}")

        try:
            matches = []
            seen_md5 = set()
            for entry in iter_archive_member_signatures(archive_path):
                md5_value = normalize_checksum(entry.get('md5', ''), 'md5')
                if md5_value in md5_lookup and md5_value not in seen_md5:
                    expected = md5_lookup[md5_value][0]
                    matches.append({
                        'member': entry.get('member') or entry.get('name'),
                        'md5': md5_value,
                        'rom_name': expected['rom_name'] or entry.get('name') or archive_path.stem,
                        'game_name': expected['game_name'],
                    })
                    seen_md5.add(md5_value)

            if not matches:
                summary['skipped'] += 1
                continue

            output_paths = set()
            with tempfile.TemporaryDirectory(prefix='rom_downloader_repack_') as temp_dir:
                temp_root = Path(temp_dir)
                prepared_outputs = []
                for match in matches:
                    rom_name = Path(match['rom_name']).name
                    target_zip = archive_path.parent / f"{Path(rom_name).stem}.zip"
                    output_paths.add(str(target_zip.resolve()).lower())

                    if (archive_path.resolve() == target_zip.resolve()
                            and len(matches) == 1
                            and Path(matches[0]['member']).name == Path(matches[0]['rom_name']).name
                            and zip_is_torrentzip_compatible(archive_path)):
                        summary['skipped'] += 1
                        continue

                    if dry_run:
                        log_func(f"  [DRY-RUN] Recompresserait: {archive_path.name} -> {target_zip.name}")
                        summary['repacked'] += 1
                        continue

                    extracted = temp_root / f"{len(prepared_outputs):04d}_{rom_name}"
                    extract_archive_member_to_file(archive_path, match['member'], extracted)
                    extracted_md5 = hash_file_signatures(extracted).get('md5')
                    if extracted_md5 != match['md5']:
                        raise RuntimeError(f"MD5 extrait incorrect pour {rom_name}")
                    prepared_outputs.append((match, extracted, rom_name, target_zip))

                for match, extracted, rom_name, target_zip in prepared_outputs:
                    comment = create_torrentzip_single_file(extracted, rom_name, target_zip)
                    ok, message = verify_downloaded_md5({'roms': [{'md5': match['md5']}]}, str(target_zip))
                    if not ok:
                        raise RuntimeError(message)
                    log_func(f"  TorrentZip OK: {target_zip.name} ({comment})")
                    summary['repacked'] += 1
                    summary['items'].append({'source': str(archive_path), 'output': str(target_zip), 'game_name': match['game_name']})

            archive_resolved = str(archive_path.resolve()).lower()
            if not dry_run and archive_path.exists() and archive_resolved not in output_paths:
                archive_path.unlink()
                summary['deleted'] += 1

        except Exception as e:
            summary['failed'] += 1
            log_func(f"  Echec nettoyage TorrentZip {archive_path.name}: {e}")

    log_func(
        "Nettoyage TorrentZip termine: "
        f"{summary['repacked']} recompresse(s), {summary['skipped']} ignore(s), "
        f"{summary['deleted']} source(s) supprimee(s), {summary['failed']} echec(s)"
    )
    return summary


__all__ = [
    'find_7z_executable',
    'patch_zip_to_torrentzip',
    'zip_is_torrentzip_compatible',
    'create_torrentzip_single_file',
    'extract_archive_member_to_file',
    'repack_verified_archives_to_torrentzip',
]