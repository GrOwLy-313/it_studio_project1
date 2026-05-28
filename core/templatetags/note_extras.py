from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    if not dictionary:
        return None
    return dictionary.get(key) or dictionary.get(str(key))


@register.filter
def get_item_exists(dictionary, key):
    if not dictionary:
        return False
    return key in dictionary or str(key) in dictionary