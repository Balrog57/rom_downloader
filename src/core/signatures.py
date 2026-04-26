import hashlib
import tempfile
import zlib
from pathlib import Path

from .dat_parser import normalize_checksum
from .dependencies import import_optional_package


def compute_stream_checksums(stream) -> tuple[str, str, str]:
    """Calcule CRC32, MD5 et SHA1 d'un flux binaire."""
    md5_hash = hashlib.md5()
    sha1_hash = hashlib.sha1()
    crc_value = 0

    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        if not chunk:
            break
        md5_hash.update(chunk)
        sha1_hash.update(chunk)
        crc_value = zlib.crc32(chunk, crc_value)

    return (
        normalize_checksum(f"{crc_value & 0xffffffff:08x}", 'crc'),
        normalize_checksum(md5_hash.hexdigest(), 'md5'),
        normalize_checksum(sha1_hash.hexdigest(), 'sha1')
    )


def index_signature_value(signature_index: dict, checksum_type: str, checksum_value: str, reference: dict):
    """Indexe une signature locale pour les comparaisons rapides."""
    normalized_value = normalize_checksum(checksum_value, checksum_type)
    if not normalized_value:
        return
    signature_index[checksum_type].setdefault(normalized_value, []).append(reference)


def build_target_signature_sets(dat_games: dict | None) -> dict:
    """Construit les ensembles de signatures presentes dans le DAT."""
    from .dat_parser import parse_rom_size
    targets = {
        'md5': set(),
        'crc': set(),
        'sha1': set(),
        'size': set()
    }
    if not dat_games:
        return targets

    for game_info in dat_games.values():
        for rom_info in game_info.get('roms', []):
            for checksum_type in ('md5', 'crc', 'sha1'):
                normalized_value = normalize_checksum(rom_info.get(checksum_type, ''), checksum_type)
                if normalized_value:
                    targets[checksum_type].add(normalized_value)
            rom_size = parse_rom_size(rom_info.get('size'))
            if rom_size is not None:
                targets['size'].add(rom_size)

    return targets


def hash_file_signatures(file_path: Path) -> dict:
    """Calcule les signatures d'un fichier local."""
    with open(file_path, 'rb') as file_handle:
        crc_value, md5_hash, sha1_hash = compute_stream_checksums(file_handle)
    return {
        'crc': crc_value,
        'md5': md5_hash,
        'sha1': sha1_hash
    }


def hash_zip_entry_signatures(zip_file, zip_info) -> dict:
    """Calcule les signatures d'une entree ZIP locale."""
    with zip_file.open(zip_info, 'r') as entry_handle:
        crc_value, md5_hash, sha1_hash = compute_stream_checksums(entry_handle)
    return {
        'crc': normalize_checksum(f"{zip_info.CRC & 0xffffffff:08x}", 'crc') or crc_value,
        'md5': md5_hash,
        'sha1': sha1_hash
    }


def iter_archive_member_signatures(file_path: Path, target_sizes: set | None = None, require_hashes: bool = True):
    """Retourne les signatures des fichiers contenus dans une archive supportee.

    Quand require_hashes=False, seules les metadonnees disponibles dans l'archive
    sont utilisees. C'est suffisant pour le scan de reprise et evite d'extraire
    des gros 7z PlayStation juste pour les comparer au DAT.
    """
    from .constants import ROM_EXTENSIONS
    suffix = file_path.suffix.lower()
    target_sizes = target_sizes or set()

    if suffix == '.zip':
        import zipfile
        with zipfile.ZipFile(file_path, 'r') as zf:
            for zip_info in zf.infolist():
                if zip_info.is_dir():
                    continue
                if target_sizes and zip_info.file_size not in target_sizes:
                    continue
                signatures = {
                    'crc': normalize_checksum(f"{zip_info.CRC & 0xffffffff:08x}", 'crc'),
                    'md5': '',
                    'sha1': ''
                }
                if require_hashes:
                    signatures = hash_zip_entry_signatures(zf, zip_info)
                yield {
                    'name': Path(zip_info.filename).name or zip_info.filename,
                    'member': zip_info.filename,
                    'size': zip_info.file_size,
                    **signatures
                }
        return

    if suffix == '.7z':
        py7zr = import_optional_package('py7zr', auto_install=True)
        if py7zr is None:
            raise RuntimeError("py7zr indisponible")
        if not require_hashes:
            with py7zr.SevenZipFile(file_path, mode='r') as archive:
                for archive_info in archive.list():
                    if getattr(archive_info, 'is_directory', False):
                        continue
                    member_size = getattr(archive_info, 'uncompressed', None)
                    if target_sizes and member_size not in target_sizes:
                        continue
                    crc_value = getattr(archive_info, 'crc32', None)
                    yield {
                        'name': Path(archive_info.filename).name or archive_info.filename,
                        'member': archive_info.filename,
                        'size': member_size,
                        'crc': normalize_checksum(f"{crc_value & 0xffffffff:08x}", 'crc') if crc_value is not None else '',
                        'md5': '',
                        'sha1': ''
                    }
            return
        with tempfile.TemporaryDirectory(prefix='rom_downloader_7z_') as temp_dir:
            with py7zr.SevenZipFile(file_path, mode='r') as archive:
                targets = [
                    archive_info.filename
                    for archive_info in archive.list()
                    if not getattr(archive_info, 'is_directory', False)
                    and (not target_sizes or getattr(archive_info, 'uncompressed', None) in target_sizes)
                ]
                if not targets:
                    return
                archive.extract(path=temp_dir, targets=targets)
            temp_root = Path(temp_dir)
            for extracted in temp_root.rglob('*'):
                if not extracted.is_file():
                    continue
                signatures = hash_file_signatures(extracted)
                yield {
                    'name': extracted.name,
                    'member': str(extracted.relative_to(temp_root)),
                    'size': extracted.stat().st_size,
                    **signatures
                }
        return

    if suffix == '.rar':
        rarfile = import_optional_package('rarfile', auto_install=True)
        if rarfile is None:
            raise RuntimeError("rarfile indisponible")
        with rarfile.RarFile(file_path, 'r') as archive:
            for rar_info in archive.infolist():
                if rar_info.isdir():
                    continue
                if target_sizes and rar_info.file_size not in target_sizes:
                    continue
                crc_header = normalize_checksum(f"{rar_info.CRC & 0xffffffff:08x}", 'crc')
                signatures = {'crc': crc_header, 'md5': '', 'sha1': ''}
                if require_hashes:
                    with archive.open(rar_info, 'r') as entry_handle:
                        crc_value, md5_hash, sha1_hash = compute_stream_checksums(entry_handle)
                    signatures = {
                        'crc': crc_header or crc_value,
                        'md5': md5_hash,
                        'sha1': sha1_hash
                    }
                yield {
                    'name': Path(rar_info.filename).name or rar_info.filename,
                    'member': rar_info.filename,
                    'size': rar_info.file_size,
                    **signatures
                }
        return

    raise RuntimeError(f"archive {suffix} non supportee")


__all__ = [
    'compute_stream_checksums',
    'index_signature_value',
    'build_target_signature_sets',
    'hash_file_signatures',
    'hash_zip_entry_signatures',
    'iter_archive_member_signatures',
]