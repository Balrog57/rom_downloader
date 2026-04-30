from .env import APP_ROOT

ROM_EXTENSIONS = (
    '.zip', '.7z', '.rar', '.gz', '.z', '.tar', '.tar.gz',
    '.gb', '.gbc', '.gba',
    '.nes', '.smc', '.sfc', '.fig',
    '.n64', '.z64', '.v64', '.ndd',
    '.nds', '.dsi', '.3ds', '.cia', '.cxi',
    '.gcm', '.rvz', '.ciso', '.gcz', '.wbfs', '.nkit.iso', '.nkit.gcm', '.nkit.rvz',
    '.sms', '.gg', '.sg',
    '.md', '.gen', '.smd',
    '.32x', '.cdx',
    '.chd', '.cue', '.iso', '.bin', '.img', '.ccd', '.sub',
    '.psx', '.psf', '.pbp', '.ecm',
    '.pce', '.pcfx',
    '.ngp', '.ngc', '.neo',
    '.lnx', '.rom', '.a26', '.a52', '.a78', '.j64', '.jag',
    '.ws', '.wsc', '.swc',
    '.vb',
    '.adf', '.adz', '.dms', '.ipf', '.hdf', '.hdz',
    '.d64', '.d6z', '.d71', '.d7z', '.d80', '.d81', '.d82', '.d8z', '.g64', '.g6z',
    '.nib', '.nbz', '.x64', '.x6z', '.crt', '.t64',
    '.dsk', '.m3u', '.mds', '.mdf', '.nrg', '.b5i', '.bwi', '.cdi', '.c2d', '.daa', '.pdi',
    '.dim', '.d88', '.88d', '.hdm', '.hdi', '.tfd', '.dfi', '.fdi',
    '.tap', '.tzx', '.cdt', '.z80', '.sna',
    '.st', '.msa',
    '.col', '.cv',
)

MINERVA_BROWSE_BASE = 'https://minerva-archive.org/browse/'
MINERVA_TORRENT_BASE_CANDIDATES = (
    'https://minerva-archive.org/assets/Minerva_Myrient_v0.3/',
    'https://minerva-archive.org/assets/',
    'https://cdn.minerva-archive.org/'
)
LOLROMS_BASE = 'https://lolroms.com/'

VIMM_BASE = 'https://vimm.net/'
RETRO_GAME_SETS_BASE = 'https://retrogamesets.fr/'
ROMHUSTLER_BASE = 'https://romhustler.org/'
COOLROM_BASE = 'https://coolrom.com.au/'
NOPAYSTATION_BASE = 'https://nopaystation.com/'
STARTGAME_BASE = 'https://startgame.world/'
HSHOP_BASE = 'https://hshop.erista.me/'
ROMSXISOS_BASE = 'https://romsxisos.github.io/'
BALROG_ASSETS_DIR = APP_ROOT / 'assets'
BALROG_WINDOW_ICON = BALROG_ASSETS_DIR / 'Retrogaming-Toolkit-AIO.ico'
BALROG_1G1R_ICON = BALROG_ASSETS_DIR / 'icon_1g1r.png'

UI_COLOR_BG = '#151515'
UI_COLOR_CARD_BG = '#1e1e1e'
UI_COLOR_CARD_BORDER = '#444444'
UI_COLOR_INPUT_BG = '#202020'
UI_COLOR_INPUT_BORDER = '#3d3d3d'
UI_COLOR_TEXT_MAIN = '#ffffff'
UI_COLOR_TEXT_SUB = '#aaaaaa'
UI_COLOR_ACCENT = '#ff6699'
UI_COLOR_ACCENT_HOVER = '#ff3385'
UI_COLOR_GHOST = '#2b2b2b'
UI_COLOR_GHOST_HOVER = '#333333'
UI_COLOR_SUCCESS = '#2ecc71'
UI_COLOR_ERROR = '#e74c3c'
UI_COLOR_WARNING = '#f39c12'

SOURCE_FAMILY_MAP = {
    'No-Intro': 'no-intro',
    'Redump': 'redump',
    'TOSEC': 'tosec'
}
MINERVA_TORRENT_AVAILABILITY = {}
MINERVA_TORRENT_URL_CACHE = {}
MINERVA_TORRENT_BACKEND_WARNING_SHOWN = False
LOLROMS_SESSION = None

__all__ = [
    'ROM_EXTENSIONS',
    'MINERVA_BROWSE_BASE',
    'MINERVA_TORRENT_BASE_CANDIDATES',
    'LOLROMS_BASE',
    'VIMM_BASE',
    'RETRO_GAME_SETS_BASE',
    'ROMHUSTLER_BASE',
    'COOLROM_BASE',
    'NOPAYSTATION_BASE',
    'STARTGAME_BASE',
    'HSHOP_BASE',
    'ROMSXISOS_BASE',
    'BALROG_ASSETS_DIR',
    'BALROG_WINDOW_ICON',
    'BALROG_1G1R_ICON',
    'UI_COLOR_BG',
    'UI_COLOR_CARD_BG',
    'UI_COLOR_CARD_BORDER',
    'UI_COLOR_INPUT_BG',
    'UI_COLOR_INPUT_BORDER',
    'UI_COLOR_TEXT_MAIN',
    'UI_COLOR_TEXT_SUB',
    'UI_COLOR_ACCENT',
    'UI_COLOR_ACCENT_HOVER',
    'UI_COLOR_GHOST',
    'UI_COLOR_GHOST_HOVER',
    'UI_COLOR_SUCCESS',
    'UI_COLOR_ERROR',
    'UI_COLOR_WARNING',
    'SOURCE_FAMILY_MAP',
    'MINERVA_TORRENT_AVAILABILITY',
    'MINERVA_TORRENT_URL_CACHE',
    'MINERVA_TORRENT_BACKEND_WARNING_SHOWN',
    'LOLROMS_SESSION',
]