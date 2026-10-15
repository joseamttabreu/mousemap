"""Tradução via gettext. As mensagens de origem estão em português do Brasil.

Instalado, os catálogos ficam em <prefixo>/share/locale; em desenvolvimento, aponte
MOUSEMAP_LOCALEDIR para um diretório com <idioma>/LC_MESSAGES/mousemap.mo.
"""

import gettext
import os

DOMAIN = "mousemap"

_translation = gettext.translation(DOMAIN, localedir=os.environ.get("MOUSEMAP_LOCALEDIR"), fallback=True)
_ = _translation.gettext
