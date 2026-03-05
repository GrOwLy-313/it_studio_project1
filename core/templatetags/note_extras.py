from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Получить значение из словаря по ключу (поддерживает int и str ключи)."""
    if not dictionary:
        return None
    return dictionary.get(key) or dictionary.get(str(key))


@register.filter
def get_item_exists(dictionary, key):
    """Проверить наличие ключа в словаре (поддерживает int и str ключи)."""
    if not dictionary:
        return False
    return key in dictionary or str(key) in dictionary