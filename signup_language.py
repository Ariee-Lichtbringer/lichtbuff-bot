"""Display localization; never changes identifiers, credentials or user content."""
import json
from pathlib import Path
EN = json.loads(Path(__file__).with_name('signup_translations.json').read_text(encoding='utf-8'))
def user_language(interaction):
    locale = getattr(interaction, 'locale', None)
    if locale is None:
        return 'de'
    value = getattr(locale, 'value', str(locale))
    return 'de' if value.lower().startswith('de') else 'en'
def guild_language(post):
    return 'en' if post.get('guild', {}).get('language') == 'en' else 'de'
def tr(text, language):
    return EN.get(text, text) if language == 'en' else text

def localize_ui(view, language):
    view.language = language
    if hasattr(view, 'title'):
        view.title = tr(view.title, language)
    def visit(item):
        for attr in ('label', 'placeholder', 'text'):
            value = getattr(item, attr, None)
            if isinstance(value, str):
                setattr(item, attr, tr(value, language))
        for option in getattr(item, 'options', []):
            option.label = tr(option.label, language)
        component = getattr(item, 'component', None)
        if component is not None:
            visit(component)
    for item in view.children:
        visit(item)
