"""Recognise the same phone or tablet across shops.

Shops name the same device differently, e.g.
  "iPhone 16 Pro Max 256GB | Chính hãng VN/A"
  "Điện thoại Apple iPhone 16 Pro Max 256GB"
  "iPhone 16 Pro Max 256GB - Titan Sa Mạc"
model_key() turns all three into "16 apple iphone max pro|256gb" so their
prices can be compared. Colours, "chính hãng", RAM and shop wording are
dropped; the storage size is kept because it changes the price.
"""
import re
import unicodedata

# Brand detection: the first matching word decides the brand.
BRANDS = {
    "apple": ("iphone", "ipad", "apple"),
    "samsung": ("samsung", "galaxy"),
    "xiaomi": ("xiaomi", "redmi", "poco"),
    "oppo": ("oppo",),
    "vivo": ("vivo",),
    "realme": ("realme",),
    "honor": ("honor",),
    "huawei": ("huawei",),
    "nokia": ("nokia",),
    "tecno": ("tecno",),
    "infinix": ("infinix",),
    "itel": ("itel",),
    "oneplus": ("oneplus",),
    "google": ("pixel",),
    "nothing": ("nothing phone",),
    "asus": ("asus", "rog phone", "zenfone"),
    "sony": ("xperia",),
    "motorola": ("motorola", "moto "),
    "lenovo": ("lenovo",),
    "masstel": ("masstel",),
    "benco": ("benco",),
    "zte": ("zte", "nubia"),
}

TABLET_WORDS = ("ipad", "tab ", "tab s", "tab a", "pad ", "pad pro", "pad se", "matepad", "tablet", "máy tính bảng")
# Clearly phones, even when a shop lists them on its tablet page.
PHONE_WORDS = ("iphone", "điện thoại", "redmi note", "galaxy a", "galaxy s", "galaxy z", "galaxy m",
               "reno", "find x", "pixel", "xperia", "rog phone", "zenfone", "nokia")

# Shop wording that is not part of the model name. "Cellular" stays: an iPad
# with mobile data is a different (dearer) model from the Wi-Fi one.
NOISE = [
    r"điện thoại( di động)?", r"máy tính bảng", r"chính hãng", r"vn/a", r"\bvn\b", r"\bll/a\b", r"\bza/a\b",
    r"nhập khẩu", r"quốc tế", r"new seal", r"nguyên seal", r"mới 100%", r"\bmới\b", r"fullbox",
    r"\(.*?\)", r"\[.*?\]", r"\bwi-?fi\b", r"\binch\b", r'"', r"\b5g\b", r"\b4g\b", r"\blte\b",
    r"\bdual sim\b", r"\b2 sim\b", r"\besim\b", r"\bsmartphone\b",
]
# Colour words (Vietnamese and English); the text after a "-" or "|" is
# usually a colour or promotion and is cut off before this list is used.
COLOURS = [
    "đen", "trắng", "xanh", "đỏ", "vàng", "tím", "hồng", "bạc", "xám", "cam", "be", "kem", "titan", "titanium",
    "black", "white", "blue", "red", "gold", "purple", "pink", "silver", "gray", "grey", "green",
    "midnight", "starlight", "graphite", "natural", "desert", "sa mạc", "tự nhiên", "ngọc", "lục",
]

STORAGE_RE = re.compile(r"(\d{1,4})\s*(gb|tb)\b", re.IGNORECASE)
RAM_STORAGE_RE = re.compile(r"(\d{1,2})\s*gb\s*[/+|-]\s*(\d{2,4})\s*(gb|tb)\b", re.IGNORECASE)


def _ascii_lower(text):
    return unicodedata.normalize("NFC", str(text)).lower()


def brand_of(name):
    low = _ascii_lower(name)
    for brand, words in BRANDS.items():
        if any(w in low for w in words):
            return brand
    return ""


def category_of(name, default="phone"):
    low = f" {_ascii_lower(name)} "
    if any(w in low for w in TABLET_WORDS):
        return "tablet"
    if any(w in low for w in PHONE_WORDS):
        return "phone"
    return default


def storage_of(name):
    """Storage in GB (1 TB = 1024), ignoring the RAM in names like '8GB/256GB'."""
    low = _ascii_lower(name)
    m = RAM_STORAGE_RE.search(low)
    if m:
        size, unit = int(m.group(2)), m.group(3)
        return size * 1024 if unit == "tb" else size
    sizes = [int(n) * (1024 if u == "tb" else 1) for n, u in STORAGE_RE.findall(low)]
    sizes = [s for s in sizes if s >= 32]  # 4GB/8GB/12GB on their own are RAM
    return max(sizes) if sizes else None


def storage_label(gb):
    if not gb:
        return ""
    return f"{gb // 1024}TB" if gb >= 1024 and gb % 1024 == 0 else f"{gb}GB"


def model_name(name):
    """The device name without shop wording, colour, RAM or storage."""
    low = _ascii_lower(name)
    low = re.split(r"\s[-|–—]\s|\|", low)[0]  # cut "... - Titan Sa Mạc" / "... | Chính hãng"
    for pat in NOISE:
        low = re.sub(pat, " ", low)
    low = RAM_STORAGE_RE.sub(" ", low)
    low = STORAGE_RE.sub(" ", low)
    low = re.sub(r"\b\d{1,2}\s*gb\b", " ", low)  # leftover RAM
    words = low.split()
    while words and words[-1] in COLOURS:
        words.pop()
    low = " ".join(words)
    for c in sorted(COLOURS, key=len, reverse=True):
        low = re.sub(rf"\b{re.escape(c)}$", "", low).strip()
    low = re.sub(r"[^\w\s]", " ", low)
    low = re.sub(r"\s+", " ", low).strip()
    brand = brand_of(name)
    if brand and not low.startswith(brand):
        low = f"{brand} {low}"
    return low


def model_key(name):
    """Same key for the same device and storage, whatever the word order
    ("iPad Air M2 11" and "iPad Air 11 M2" are one model)."""
    gb = storage_of(name)
    words = " ".join(sorted(set(model_name(name).split())))
    return f"{words}|{storage_label(gb).lower()}"


def display_name(name):
    """A tidy name to show for a model group."""
    m = model_name(name)
    words = []
    for w in m.split():
        if w in ("iphone", "ipad"):
            words.append("i" + w[1:].capitalize())
        elif re.fullmatch(r"[a-z]?\d+[a-z]*", w) or len(w) <= 2:
            words.append(w.upper())
        else:
            words.append(w.capitalize())
    gb = storage_of(name)
    return " ".join(words) + (f" {storage_label(gb)}" if gb else "")
