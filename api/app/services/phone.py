import re


def _pad_040_compact(digits: str) -> str | None:
    """0404590002 (10) and 04045900002 (11) are the same ExoPhone on Exotel."""
    if digits.startswith("0") and len(digits) == 10 and digits.startswith("040"):
        return digits[:-1] + "0" + digits[-1]
    return None


def _landline_digit_forms(digits: str) -> set[str]:
    """Hyderabad 040 ExoPhones: Exotel may send 0404590002 or 04045900002."""
    forms: set[str] = {digits}
    padded = _pad_040_compact(digits)
    if padded:
        forms.add(padded)
    d = digits[1:] if digits.startswith("0") else digits
    if d.startswith("40") and len(d) == 9:
        padded = d[:2] + "0" + d[2:]
        forms.add("0" + padded)
        forms.add(padded)
    if d.startswith("40") and len(d) == 10:
        forms.add("0" + d)
    return forms


def normalize_e164(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        raise ValueError("invalid phone")
    compact_pad = _pad_040_compact(digits)
    if compact_pad:
        digits = compact_pad
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    if len(digits) == 10 and not digits.startswith("0"):
        return f"+91{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"+91{digits[1:]}"
    if digits.startswith("40") and len(digits) == 10:
        return f"+91{digits}"
    return f"+{digits}"


def national_exophone_display(phone: str) -> str:
    """Local India dial string (040…), not +91."""
    raw = phone.strip()
    if raw.startswith("0") and not raw.startswith("+"):
        return raw
    try:
        e164 = normalize_e164(phone)
    except ValueError:
        return raw
    digits = e164[1:]
    if digits.startswith("91") and len(digits) == 12:
        national = f"0{digits[2:]}"
        # Exotel UI: 0404590002 vs stored 04045900002
        if national.startswith("040") and len(national) == 11 and national[9] == "0":
            return national[:9] + national[10:]
        return national
    return raw


def e164_variants(phone: str) -> set[str]:
    """Compare ExoPhone values across +91, 0-prefixed, and bare 10-digit forms."""
    raw_digits = re.sub(r"\D", "", phone)
    digit_aliases: set[str] = {raw_digits} if raw_digits else set()
    if raw_digits:
        digit_aliases |= _landline_digit_forms(raw_digits)
    out: set[str] = set()
    for form in digit_aliases:
        try:
            out.add(normalize_e164(form))
        except ValueError:
            pass
        if form:
            out.add(f"+{form}")
            if form.startswith("0") and len(form) >= 10:
                out.add(f"+91{form[1:]}")
            if len(form) == 10 and not form.startswith("0"):
                out.add(f"+91{form}")
            if form.startswith("91") and len(form) == 12:
                out.add(f"+{form}")
    return {x for x in out if len(x) > 4}