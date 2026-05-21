"""Tests unitaires pour download_single_game et auto_extract_and_repack."""

from pathlib import Path
import sys
import tempfile
import zipfile
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.download_single import auto_extract_and_repack
from src.core.verification import verify_downloaded_md5, expected_game_md5_values
from src.core.torrentzip import (
    create_torrentzip_single_file,
    extract_archive_member_to_file,
    zip_is_torrentzip_compatible,
)
from src.core.signatures import hash_file_signatures
from src.core.scanner import build_dat_md5_lookup


def assert_true(condition, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    # -- auto_extract_and_repack: fichier inexistant
    result = auto_extract_and_repack(
        downloaded_path='/nonexistent/file.7z',
        game_info={'game_name': 'Test', 'roms': []},
        dat_games={},
        output_folder=tempfile.gettempdir(),
        clean_torrentzip=True,
        log_func=lambda _: None,
    )
    assert_true(not result['md5_ok'], "fichier inexistant doit echouer MD5")
    assert_true(result['md5_message'] == 'Fichier telecharge introuvable', "message fichier introuvable")
    assert_true(result['final_paths'] == [], "pas de chemins finaux si fichier introuvable")

    # -- auto_extract_and_repack: fichier brut (pas archive)
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_path = Path(tmp_dir) / "game.bin"
        rom_path.write_bytes(b"HELLO ROM TEST" * 10)
        sigs = hash_file_signatures(str(rom_path))

        game_info = {
            'game_name': 'Test Game',
            'roms': [{'name': 'game.bin', 'size': rom_path.stat().st_size, 'md5': sigs['md5'], 'crc': '', 'sha1': ''}]
        }
        result = auto_extract_and_repack(
            downloaded_path=str(rom_path),
            game_info=game_info,
            dat_games={'Test Game': game_info},
            output_folder=tmp_dir,
            clean_torrentzip=True,
            log_func=lambda _: None,
        )
        assert_true(result['md5_ok'], "MD5 doit etre OK pour un fichier brut")
        assert_true(result['final_paths'] == [str(rom_path)], "fichier brut renomme tel quel")
        assert_true(not result['extracted'], "pas d'extraction pour fichier brut")
        assert_true(result['repacked'] == 0, "pas de repack pour fichier brut")

    # -- auto_extract_and_repack: fichier brut sans MD5 DAT
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_path = Path(tmp_dir) / "game2.bin"
        rom_path.write_bytes(b"NO MD5 TEST" * 10)

        game_info = {'game_name': 'NoMD5 Game', 'roms': [{'name': 'game2.bin', 'size': rom_path.stat().st_size}]}
        result = auto_extract_and_repack(
            downloaded_path=str(rom_path),
            game_info=game_info,
            dat_games={'NoMD5 Game': game_info},
            output_folder=tmp_dir,
            clean_torrentzip=True,
            log_func=lambda _: None,
        )
        assert_true(result['md5_ok'], "MD5 ignore si absent du DAT")
        assert_true(result['final_paths'] == [str(rom_path)], "fichier sans MD5 DAT renomme tel quel")

    # -- auto_extract_and_repack: ZIP avec ROM, clean_torrentzip=False
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_content = b"ZIP ROM TEST CONTENT" * 50
        rom_md5 = hash_file_signatures_data(rom_content)
        rom_path = Path(tmp_dir) / "inner_rom.bin"
        rom_path.write_bytes(rom_content)
        zip_path = Path(tmp_dir) / "game.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(str(rom_path), arcname='inner_rom.bin')

        game_info = {
            'game_name': 'Zip Game',
            'roms': [{'name': 'inner_rom.bin', 'size': len(rom_content), 'md5': rom_md5, 'crc': '', 'sha1': ''}]
        }
        result = auto_extract_and_repack(
            downloaded_path=str(zip_path),
            game_info=game_info,
            dat_games={'Zip Game': game_info},
            output_folder=tmp_dir,
            clean_torrentzip=False,
            log_func=lambda _: None,
        )
        assert_true(result['md5_ok'], "MD5 OK dans ZIP")
        assert_true(result['final_paths'] == [str(zip_path)], "clean_torrentzip=False garde le ZIP")
        assert_true(not result['extracted'], "pas d'extraction si clean_torrentzip=False")

    # -- auto_extract_and_repack: ZIP avec ROM, clean_torrentzip=True
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_content = b"TZ ROM TEST CONTENT FOR TORRENTZIP" * 50
        rom_md5 = hash_file_signatures_data(rom_content)
        rom_path = Path(tmp_dir) / "inner_tz.bin"
        rom_path.write_bytes(rom_content)
        zip_path = Path(tmp_dir) / "game_tz.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(str(rom_path), arcname='inner_tz.bin')

        game_info = {
            'game_name': 'TZ Game',
            'roms': [{'name': 'inner_tz.bin', 'size': len(rom_content), 'md5': rom_md5, 'crc': '', 'sha1': ''}]
        }
        result = auto_extract_and_repack(
            downloaded_path=str(zip_path),
            game_info=game_info,
            dat_games={'TZ Game': game_info},
            output_folder=tmp_dir,
            clean_torrentzip=True,
            log_func=lambda _: None,
        )
        assert_true(result['md5_ok'], "MD5 OK avant TorrentZip")
        assert_true(result['extracted'], "extraction effectuee")
        assert_true(result['repacked'] >= 1, "au moins 1 ZIP TorrentZip cree")
        assert_true(len(result['final_paths']) >= 1, "au moins 1 chemin final")
        tz_path = result['final_paths'][0]
        assert_true(Path(tz_path).exists(), "fichier TorrentZip final existe")
        assert_true(tz_path.endswith('.zip'), "fichier final est un .zip")
        assert_true(not Path(zip_path).exists() or str(zip_path) == tz_path, "archive source supprimee ou identique au final")

    # -- auto_extract_and_repack: MD5 incorrect
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_path = Path(tmp_dir) / "bad.bin"
        rom_path.write_bytes(b"BAD CONTENT" * 10)
        game_info = {
            'game_name': 'Bad Game',
            'roms': [{'name': 'bad.bin', 'size': rom_path.stat().st_size, 'md5': 'deadbeefdeadbeefdeadbeefdeadbeef', 'crc': '', 'sha1': ''}]
        }
        result = auto_extract_and_repack(
            downloaded_path=str(rom_path),
            game_info=game_info,
            dat_games={'Bad Game': game_info},
            output_folder=tmp_dir,
            clean_torrentzip=True,
            log_func=lambda _: None,
        )
        assert_true(not result['md5_ok'], "MD5 incorrect doit echouer")
        assert_true(result['final_paths'] == [], "pas de chemins finaux si MD5 KO")

    # -- verify_downloaded_md5: fichier absent de DAT (pas de MD5/taille)
    ok, msg = verify_downloaded_md5({'roms': []}, '/nonexistent')
    assert_true(ok, "pas de MD5/taille = validation ignoree")
    assert_true("absent" in msg.lower() or "ignoree" in msg.lower(), "message validation ignoree")

    # -- verify_downloaded_md5: verification taille only
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_path = Path(tmp_dir) / "size_test.bin"
        rom_path.write_bytes(b"ABCD")
        ok, msg = verify_downloaded_md5({'roms': [{'size': '4'}]}, str(rom_path))
        assert_true(ok and "Taille DAT OK" in msg, "verification taille seule OK")

        ok2, msg2 = verify_downloaded_md5({'roms': [{'size': '5'}]}, str(rom_path))
        assert_true(not ok2 and "Taille DAT KO" in msg2, "verification taille KO")

    # -- verify_downloaded_md5: verification MD5 + taille dans ZIP
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_content = b"MD5 ZIP TEST" * 10
        rom_md5 = hash_file_signatures_data(rom_content)
        rom_path = Path(tmp_dir) / "md5_test.bin"
        rom_path.write_bytes(rom_content)
        zip_path = Path(tmp_dir) / "md5_test.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.write(str(rom_path), arcname='md5_test.bin')

        ok, msg = verify_downloaded_md5(
            {'roms': [{'name': 'md5_test.bin', 'size': str(len(rom_content)), 'md5': rom_md5}]},
            str(zip_path),
        )
        assert_true(ok and "MD5 OK" in msg, "MD5 + taille OK dans ZIP")

    # -- expected_game_md5_values
    md5s = expected_game_md5_values({'roms': [{'md5': 'abc123'}, {'md5': 'def456'}]})
    assert_true(md5s == {'abc123', 'def456'}, "expected_game_md5_values extrait les MD5")

    md5s_empty = expected_game_md5_values({'roms': []})
    assert_true(md5s_empty == set(), "expected_game_md5_values vide si pas de ROMs")

    # -- zip_is_torrentzip_compatible
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_path = Path(tmp_dir) / "tz_compat.bin"
        rom_path.write_bytes(b"TZ COMPAT TEST" * 10)

        normal_zip = Path(tmp_dir) / "normal.zip"
        with zipfile.ZipFile(normal_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.write(str(rom_path), arcname='tz_compat.bin')
        assert_true(not zip_is_torrentzip_compatible(normal_zip), "ZIP normal n'est pas TorrentZip")

    # -- create_torrentzip_single_file
    with tempfile.TemporaryDirectory(prefix='rom_dl_test_') as tmp_dir:
        rom_path = Path(tmp_dir) / "tz_single.bin"
        rom_path.write_bytes(b"TZ SINGLE TEST" * 50)
        target_zip = Path(tmp_dir) / "tz_single.zip"
        comment = create_torrentzip_single_file(rom_path, 'tz_single.bin', target_zip)
        assert_true(target_zip.exists(), "TorrentZip ZIP cree")
        assert_true(comment and "TORRENTZIPPED" in comment.upper(), "commentaire TorrentZip present")

    # -- build_dat_md5_lookup
    dat_games = {
        'Game A': {'game_name': 'Game A', 'roms': [{'name': 'a.bin', 'md5': 'aaa111', 'size': '4'}]},
        'Game B': {'game_name': 'Game B', 'roms': [{'name': 'b.bin', 'md5': 'bbb222', 'size': '8'}]},
    }
    lookup = build_dat_md5_lookup(dat_games)
    assert_true('aaa111' in lookup, "MD5 aaa111 dans lookup")
    assert_true('bbb222' in lookup, "MD5 bbb222 dans lookup")
    assert_true(lookup['aaa111'][0]['rom_name'] == 'a.bin', "rom_name correct dans lookup")

    print("download_single checks ok")


def hash_file_signatures_data(data: bytes) -> str:
    import hashlib
    return hashlib.md5(data).hexdigest()


if __name__ == "__main__":
    main()
