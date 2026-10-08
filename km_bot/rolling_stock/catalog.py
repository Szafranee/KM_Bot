"""Human-friendly descriptions of the rolling stock codes used in KM PDFs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VehicleType:
    code_prefix: str
    name: str
    full_name: str
    image: str | None = None
    seats: int | None = None
    max_speed: int | None = None
    is_locomotive: bool = False


# Order matters: the first matching prefix wins, so more specific codes go first.
VEHICLES: tuple[VehicleType, ...] = (
    VehicleType("ER75", "Flirt", "Stadler FLIRT (ER75)", "flirt_1.jpg", 183, 160),
    VehicleType("ER160", "Flirt 3", "Stadler FLIRT3 (ER160)", "flirt_3.jpg", 269, 160),
    VehicleType("45WE", "Impuls", "Newag Impuls (45WE)", "impuls.jpg", 219, 160),
    VehicleType("EN76", "Elf", "Pesa Elf (EN76)", "elf.jpg", 183, 160),
    VehicleType("SA135", "SA135", "Pesa SA135", "sa135.jpg", 68, 120),
    VehicleType("SA222", "SA222", "Newag 222M (SA222)", "sa222.jpg", 126, 130),
    VehicleType("222M", "SA222", "Newag 222M (SA222)", "sa222.jpg", 126, 130),
    VehicleType("VT627", "Vt627", "Duewag VT627", "vt627.jpg", 70, 80),
    VehicleType("VT628", "Vt628", "Duewag VT628", None, 144, 120),
    VehicleType("SN82", "SN82 (dzierżawiony od SKPL)", "SN82", "sn82.jpg"),
    VehicleType("EN57AKM", "Kibel AKM", "Pafawag EN57AKM", "en_57akm.jpg", 188, 120),
    VehicleType("EN57AL", "Kibel AL", "Pafawag EN57AL", "en_57al.jpg", 171, 120),
    VehicleType("EN57", "The Kibel", "Pafawag EN57", "en_57.jpg", None, 110),
    VehicleType("EN71", "Kibel EN71", "Pafawag EN71", "en_71.jpg", 268, 110),
    VehicleType("EW60", "EW60", "Pafawag EW60", None, 176, 120),
    VehicleType("EU47", "EU47", "Bombardier TRAXX P160 DC (EU47)", "eu47.jpg", None, 160, True),
    VehicleType("111EB", "Gama 111Eb", "Pesa Gama (111Eb)", None, None, 160, True),
)

DEFAULT_IMAGE = "default_pic.jpg"
# Coach codes used for locomotive-hauled sets (Bombardier double-deck coaches).
COACH_CODES = {"B", "BS", "P", "PS", "BD", "BDH", "A", "AB"}


@dataclass(frozen=True)
class StockDescription:
    label: str
    """Short label, e.g. '2× Flirt 3' or 'EU47 + 6 wagonów piętrowych'."""
    details: str
    """Longer description with manufacturer, seats and maximum speed."""
    image: str | None
    raw: str


def find_vehicle(code: str) -> VehicleType | None:
    normalized = code.strip().upper()
    for vehicle in VEHICLES:
        if normalized.startswith(vehicle.code_prefix.upper()):
            return vehicle
    return None


def _coaches_label(count: int, double_deck: bool) -> str:
    if count == 1:
        words = ("wagon", "piętrowy")
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        words = ("wagony", "piętrowe")
    else:
        words = ("wagonów", "piętrowych")
    return f"{count} {words[0]} {words[1]}" if double_deck else f"{count} {words[0]}"


def _parse_units(units: str, size: int) -> list[int | None]:
    values: list[int | None] = []
    for part in units.split(","):
        part = part.strip()
        values.append(int(part) if part.isdigit() and int(part) > 0 else None)
    return (values + [None] * size)[:size]


def describe(stock: str, units: str = "") -> StockDescription:
    """Turns ('EU47, B, Bs', '1, 4, 1') into 'EU47 + 5 wagonów piętrowych'."""
    codes = [code.strip() for code in stock.split(",") if code.strip()]
    if not codes:
        return StockDescription("brak danych", "", None, stock)
    counts = _parse_units(units, len(codes))

    labels: list[str] = []
    details: list[str] = []
    image: str | None = None
    coaches = 0
    for code, count in zip(codes, counts, strict=True):
        if code.upper() in COACH_CODES:
            coaches += count or 1
            continue
        vehicle = find_vehicle(code)
        name = vehicle.name if vehicle else code
        prefix = f"{count}× " if count and count > 1 else ""
        labels.append(f"{prefix}{name}")
        if vehicle:
            image = image or vehicle.image
            info = [vehicle.full_name]
            if vehicle.seats:
                info.append(f"{vehicle.seats} miejsc siedzących" + (" na jednostkę" if count and count > 1 else ""))
            if vehicle.max_speed:
                info.append(f"do {vehicle.max_speed} km/h")
            details.append(", ".join(info))
        else:
            details.append(code)
    if coaches:
        labels.append(_coaches_label(coaches, double_deck=codes[0].upper().startswith("EU47")))
    return StockDescription(" + ".join(labels), "; ".join(details), image, stock)
