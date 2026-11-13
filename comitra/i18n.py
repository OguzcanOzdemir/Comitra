"""Minimal translation layer: English source strings, Turkish dictionary.

``tr("Search")`` returns the Turkish text when the UI language is Turkish.
Format placeholders are kept: ``tr("{n} results").format(n=5)``.
"""

from __future__ import annotations

import locale
import os

_lang = "en"

TR: dict[str, str] = {
    # menus
    "&File": "&Dosya", "&Search": "&Arama", "&View": "&Görünüm", "&Tools": "A&raçlar", "&Help": "&Yardım",
    "Add folder…": "Klasör ekle…", "Update index": "İndeksi güncelle", "Update index with fetch": "Fetch ile güncelle",
    "Full re-check": "Tam yeniden kontrol", "Cancel update": "Güncellemeyi durdur",
    "Export results…": "Sonuçları dışa aktar…", "Quit": "Çıkış",
    "Focus search": "Aramaya odaklan", "Clear search": "Aramayı temizle", "Save search…": "Aramayı kaydet…",
    "Saved searches": "Kayıtlı aramalar", "Recent searches": "Son aramalar", "Manage saved searches…": "Kayıtlı aramaları yönet…",
    "Group by": "Grupla", "No grouping": "Gruplama yok", "Repository": "Repo", "Author": "Yazar", "Day": "Gün",
    "Theme": "Tema", "System": "Sistem", "Light": "Açık", "Dark": "Koyu",
    "Show filter panel": "Filtre panelini göster", "Show detail panel": "Detay panelini göster",
    "Repositories…": "Repolar…", "Statistics…": "İstatistikler…", "Settings…": "Ayarlar…",
    "Last update report…": "Son güncelleme raporu…",
    "Keyboard shortcuts": "Klavye kısayolları", "About Comitra": "Comitra hakkında", "Query syntax": "Sorgu sözdizimi",
    # search bar
    "Search commits…  e.g.  author:ahmet branch:feature/* date:7d \"payment error\" -wip":
        "Commit ara…  ör.  author:ahmet branch:feature/* date:7d \"ödeme hatası\" -wip",
    "Sort": "Sırala", "Newest": "En yeni", "Oldest": "En eski", "Relevance": "En alakalı", "Auto": "Otomatik",
    # filter panel
    "Filters": "Filtreler", "Authors": "Yazarlar", "Add author (name or e-mail)…": "Yazar ekle (ad veya e-posta)…",
    "Date": "Tarih", "Any time": "Tüm zamanlar", "Today": "Bugün", "Yesterday": "Dün", "Last 7 days": "Son 7 gün",
    "Last 30 days": "Son 30 gün", "This month": "Bu ay", "This year": "Bu yıl", "Single day": "Tek gün",
    "Date range": "Tarih aralığı", "From": "Başlangıç", "To": "Bitiş",
    "Repositories": "Repolar", "Filter repositories…": "Repo filtrele…", "Branch": "Branch",
    "Branch patterns, e.g. main, feature/*": "Branch desenleri, ör. main, feature/*",
    "Commit hash": "Commit hash", "Full or short hash": "Tam veya kısa hash",
    "Changed file": "Değişen dosya", "e.g. *.py, src/auth/": "ör. *.py, src/auth/",
    "Merge commits": "Merge commit'ler", "Show": "Göster", "Hide": "Gizle", "Only merges": "Sadece merge",
    "Time of day": "Saat aralığı", "Any": "Hepsi", "Weekdays": "Haftanın günleri",
    "Mon": "Pzt", "Tue": "Sal", "Wed": "Çar", "Thu": "Per", "Fri": "Cum", "Sat": "Cmt", "Sun": "Paz",
    "Commits no longer on any branch": "Artık hiçbir branch'te olmayan commit'ler",
    "Include": "Dahil et", "Only these": "Sadece bunlar",
    "Reset filters": "Filtreleri sıfırla", "Remove": "Kaldır",
    # results
    "Hash": "Hash", "Message": "Mesaj", "Repo": "Repo", "Branch / ref": "Branch / ref",
    "{n} results": "{n} sonuç", "{n} results (limit reached)": "{n} sonuç (sınıra ulaşıldı)",
    "in {ms} ms": "{ms} ms", "No results": "Sonuç yok", "commits": "commit",
    "not on any branch": "hiçbir branch'te değil",
    # detail
    "Details": "Detaylar", "Diff": "Diff", "Copy hash": "Hash'i kopyala", "Copy message": "Mesajı kopyala",
    "Open folder": "Klasörde aç", "Open terminal": "Terminalde aç", "Open in editor": "Editörde aç",
    "Committer": "Commit eden", "Author date": "Yazım tarihi", "Commit date": "Commit tarihi",
    "Parents": "Ebeveynler", "Co-authors": "Ortak yazarlar", "Found via": "Bulunduğu ref",
    "Contained in": "İçeren branch'ler", "Changed files": "Değişen dosyalar", "Loading…": "Yükleniyor…",
    "Repository folder is not available.": "Repo klasörüne erişilemiyor.",
    "Select a commit to see its details.": "Detayları görmek için bir commit seçin.",
    "This commit is no longer reachable from any branch (force-push, rebase or deleted branch).":
        "Bu commit artık hiçbir branch'ten erişilebilir değil (force-push, rebase veya silinmiş branch).",
    "Could not load: {err}": "Yüklenemedi: {err}", "Hash copied": "Hash kopyalandı",
    # status / indexing
    "Ready": "Hazır", "Scanning folders… {cur}": "Klasörler taranıyor… {cur}",
    "Indexing {done}/{total}: {cur}": "İndeksleniyor {done}/{total}: {cur}",
    "Index updated: {new} new commits in {secs:.1f}s": "İndeks güncellendi: {secs:.1f} sn'de {new} yeni commit",
    "{n} repositories, {c} commits": "{n} repo, {c} commit",
    "Update cancelled": "Güncelleme durduruldu",
    "git was not found": "git bulunamadı",
    "Comitra needs git. Install it from https://git-scm.com (or with your package manager) and restart, or set the path to git in Settings.":
        "Comitra'nın çalışması için git gerekli. https://git-scm.com adresinden (veya paket yöneticinizle) kurup uygulamayı yeniden başlatın ya da Ayarlar'dan git yolunu belirtin.",
    "Update report": "Güncelleme raporu", "Status": "Durum", "New": "Yeni", "Unreachable": "Erişilemez",
    "Fetch": "Fetch", "Seconds": "Saniye", "Path": "Yol",
    "updated": "güncellendi", "unchanged": "değişmedi", "error": "hata", "missing": "bulunamadı",
    "cancelled": "durduruldu", "ok": "tamam", "timeout": "zaman aşımı", "auth": "yetki", "network": "ağ",
    "lock": "kilit", "inactive": "pasif", "new": "yeni",
    "{u} updated, {s} unchanged, {e} errors, {m} missing, {f} fetch problems":
        "{u} güncellendi, {s} değişmedi, {e} hata, {m} bulunamadı, {f} fetch sorunu",
    "Scan problems": "Tarama sorunları", "Close": "Kapat",
    # welcome
    "Welcome to Comitra": "Comitra'ya hoş geldiniz",
    "Add the folders that contain your git repositories. Comitra finds every repository inside them and indexes the commits of all branches. Everything stays on this computer.":
        "Git repolarınızın bulunduğu klasörleri ekleyin. Comitra içlerindeki tüm repoları bulur ve tüm branch'lerdeki commit'leri indeksler. Hiçbir veri bu bilgisayardan dışarı çıkmaz.",
    "Add folder": "Klasör ekle", "Choose a folder with git repositories": "Git repolarının olduğu bir klasör seçin",
    # settings
    "Settings": "Ayarlar", "Folders": "Klasörler", "Indexing": "İndeksleme", "Search & display": "Arama ve görünüm",
    "Integrations": "Entegrasyonlar", "Folders to scan": "Taranacak klasörler", "Add…": "Ekle…",
    "Excluded folder names (one per line)": "Atlanacak klasör adları (her satıra bir tane)",
    "Excluded paths (one per line)": "Atlanacak yollar (her satıra bir tane)",
    "Maximum folder depth": "En fazla klasör derinliği", "Follow symbolic links": "Sembolik linkleri takip et",
    "Include bare repositories": "Bare repoları dahil et",
    "Parallel workers": "Paralel işçi sayısı", "Index tags": "Tag'leri indeksle",
    "Index remote branches": "Uzak branch'leri indeksle",
    "Index changed file paths (enables file: search, slower first indexing)":
        "Değişen dosya yollarını indeksle (file: aramasını açar, ilk indeksleme yavaşlar)",
    "Keep commits that are no longer on any branch": "Artık hiçbir branch'te olmayan commit'leri sakla",
    "Run 'git fetch --all' before updating (needs network)": "Güncellemeden önce 'git fetch --all' çalıştır (ağ gerekir)",
    "Fetch timeout (seconds)": "Fetch zaman aşımı (saniye)", "Parallel fetches": "Paralel fetch sayısı",
    "Update index on start": "Açılışta indeksi güncelle",
    "Update automatically every (minutes, 0 = off)": "Otomatik güncelleme aralığı (dakika, 0 = kapalı)",
    "Watch repositories for changes": "Repolardaki değişiklikleri izle",
    "Date used for filters and sorting": "Filtre ve sıralamada kullanılan tarih",
    "Author date (when it was written)": "Yazım tarihi (author date)", "Commit date (when it was applied)": "Commit tarihi (committer date)",
    "Language": "Dil", "Automatic": "Otomatik", "Restart required for language change.": "Dil değişikliği için yeniden başlatma gerekir.",
    "git executable (empty = automatic)": "git programı (boş = otomatik)",
    "Terminal command (empty = automatic, {path} = folder)": "Terminal komutu (boş = otomatik, {path} = klasör)",
    "Editor command (empty = automatic, {path} = folder)": "Editör komutu (boş = otomatik, {path} = klasör)",
    "Browse…": "Gözat…", "Data location": "Veri konumu", "Portable mode": "Taşınabilir mod",
    "Compact database": "Veritabanını sıkıştır", "Database compacted.": "Veritabanı sıkıştırıldı.",
    "Show commits no longer on any branch by default": "Hiçbir branch'te olmayan commit'leri varsayılan olarak göster",
    "Yes": "Evet", "No": "Hayır",
    # repos dialog
    "Commits": "Commit", "Last indexed": "Son indeksleme", "never": "hiç",
    "Re-index selected": "Seçilenleri yeniden indeksle", "Remove from index": "İndeksten kaldır",
    "Exclude and remove": "Hariç tut ve kaldır", "Search in this repository": "Bu repoda ara",
    "Remove {n} repositories and their commits from the index?": "{n} repo ve commit'leri indeksten kaldırılsın mı?",
    # saved
    "Name": "Ad", "Query": "Sorgu", "Name for this search:": "Bu arama için bir ad:", "Delete": "Sil", "Run": "Çalıştır",
    "Clear recent searches": "Son aramaları temizle",
    # stats
    "Statistics": "İstatistikler", "Overview": "Genel", "By repository": "Repoya göre", "By author": "Yazara göre",
    "By month": "Aya göre", "By weekday": "Haftanın gününe göre", "By hour": "Saate göre",
    "Current results only": "Sadece mevcut sonuçlar", "Total commits": "Toplam commit", "Authors": "Yazarlar",
    "First commit": "İlk commit", "Last commit": "Son commit", "Month": "Ay", "Hour": "Saat", "Count": "Sayı",
    "E-mail": "E-posta",
    # export
    "Export": "Dışa aktar", "Exported {n} commits to {path}": "{n} commit {path} dosyasına aktarıldı",
    "Export failed: {err}": "Dışa aktarma başarısız: {err}",
    # misc
    "Comitra – search commits across all your local git repositories.": "Comitra – bilgisayarınızdaki tüm git repolarında commit arayın.",
    "Version {v}": "Sürüm {v}", "Works fully offline. Your data never leaves this computer.":
        "Tamamen çevrimdışı çalışır. Verileriniz bu bilgisayardan dışarı çıkmaz.",
    "Could not open: {err}": "Açılamadı: {err}",
    "Warning": "Uyarı", "Error": "Hata",
    "An update is already running.": "Zaten bir güncelleme çalışıyor.",
}


def set_language(lang: str) -> None:
    global _lang
    if lang == "auto":
        lang = detect_language()
    _lang = lang if lang in ("tr", "en") else "en"


def detect_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(var, "")
        if v:
            return "tr" if v.lower().startswith("tr") else "en"
    try:
        from PySide6.QtCore import QLocale

        return "tr" if QLocale.system().name().lower().startswith("tr") else "en"
    except Exception:  # pragma: no cover - Qt not available
        pass
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    return "tr" if loc.lower().startswith("tr") else "en"


def current_language() -> str:
    return _lang


def tr(text: str) -> str:
    if _lang == "tr":
        return TR.get(text, text)
    return text
