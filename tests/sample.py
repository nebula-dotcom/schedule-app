"""Data contoh untuk tes (jadwal terisi penuh, mulai 20 Nov 2026). Isi bawaan halaman web kini kosong; lihat payload_kosong()."""

HOURS = {"P": "09.00–17.00", "S": "11.30–19.30", "R": "16.30–00.30", "L": "Tidak bertugas"}


def _staff(text):
    out = []
    for item in text.split(","):
        name, shifts = item.split(":")
        out.append({"name": name, "shifts": shifts})
    return out


def payload(start="2026-11-20"):
    return {
        "start": start,
        "divisions": [
            {"key": "BAR", "title": "Bar", "hours": dict(HOURS), "staff": _staff(
                "Sadewa:PPPLSPSSSSLRRR,Ana:SSSRLRRRRRPLSP,Cecel:RRRPPLPPPPSSLS,"
                "Iman:PPPSSSLSSSRRRL,Rifky:LSSRRRRLRRPPPP")},
            {"key": "FLOOR", "title": "Floor", "hours": dict(HOURS), "staff": _staff(
                "Apen:PPPLSSSSSSLRRR,Rosi:SSSRLRRRRRPLPP,Silvi:RRRPPLPPPPSSLS,"
                "Nindya:PPPSSSLSSSRRRL,Dinar:LSSRRRRLRRPPPP,Carmel:RLRPPPPPLPSSSS")},
            {"key": "CASHIER", "title": "Cashier", "hours": dict(HOURS), "staff": _staff(
                "Leli:PPPLSSSSSSLRRR,Ririn:SSSRLRRRRRPLPP,Ike:RRRPPLPPPPSSLS")},
            {"key": "KITCHEN", "title": "Kitchen", "hours": dict(HOURS), "staff": _staff(
                "Kitchen 1:PPPLSSSSSSLRRR,Kitchen 2:SSSRLRRRRRPLPP,Kitchen 3:RRRPPLPPPPSSLS,"
                "Kitchen 4:PPPSSSLSSSRRRL,Kitchen 5:LSSRRRRLRRPPPP,Kitchen 6:RLRPPPPPLPSSSS,"
                "Kitchen 7:PPLSSSSSSLRRRR")},
        ],
    }


def payload_kosong(start="2026-11-20"):
    """Seperti isi bawaan halaman web: semua nama ada, semua sel shift kosong ("-")."""
    p = payload(start)
    for d in p["divisions"]:
        for st in d["staff"]:
            st["shifts"] = "-" * 14
    return p
