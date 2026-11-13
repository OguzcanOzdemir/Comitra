# Comitra – Görev Listesi

Durum: ✅ tamamlandı · 🔜 sıradaki · 💡 fikir

## 1. Çekirdek (core)

- ✅ Güvenli git çağrı katmanı (UTF-8, istem yok, `GIT_OPTIONAL_LOCKS=0`, zaman aşımı, `--stdin`, Windows'ta konsol penceresi yok)
- ✅ git'i bulma (PATH + bilinen kurulum yerleri + ayardan elle yol) ve anlaşılır "git yok" uyarısı
- ✅ Scanner: normal repo, submodule, bare repo; worktree tekilleştirme; atlanacak klasör adları ve yollar; derinlik sınırı; sembolik link döngüsü koruması
- ✅ SQLite şeması, WAL, migration altyapısı (`PRAGMA user_version`)
- ✅ Türkçe ve aksan duyarsız, uzunluk koruyan metin normalizasyonu
- ✅ FTS5 tam metin indeksi (normalize mesaj)
- ✅ Ref tabanlı artımlı indeksleme (`log yeni --not eski`)
- ✅ Erişilemez commit takibi (force-push, rebase, silinen branch), silmeden işaretleme, geri gelince düzeltme
- ✅ `git gc` sonrası kaybolan uçlarda tam erişilebilirlik taraması
- ✅ Taşınan repoyu kök commit ve remote ile tanıma
- ✅ Kaybolan (`missing`) ve kapsam dışı (`inactive`) repo durumları
- ✅ `.mailmap` ve `Co-authored-by` desteği
- ✅ İki tarih (author/committer), saat dilimi, yerel saat/gün
- ✅ İsteğe bağlı değişen dosya indeksi (yol sözlüğüyle)
- ✅ Paralel indeksleme, tek yazıcı, toplu transaction
- ✅ Güvenli fetch (prune yok, BatchMode, zaman aşımı, kilit tekrar denemesi, hata sınıflandırma)
- ✅ Sorgu dili: ayrıştırıcı ve kanonik metne geri çevirme (round-trip), Türkçe takma adlar
- ✅ Arama servisi: FTS + filtreler, branch çözümleme ve önbelleği, dışlama, hash ön eki, sıralama, gruplama
- ✅ İstatistik ve CSV/JSON dışa aktarma

## 2. Komut satırı

- ✅ `add`, `remove`, `roots`, `update [--fetch] [--full]`, `search`, `repos`, `stats`, `info`
- ✅ `search --format table|json|csv --group repo|author|day`

## 3. Arayüz (PySide6)

- ✅ Ana pencere: arama kutusu, sıralama, gruplama, kayıtlı aramalar menüsü
- ✅ Filtre paneli (yazar otomatik tamamlama, tarih hazır seçenekleri ve takvim, repo çoklu seçim, branch, hash, dosya, merge, saat, gün, erişilemez commit'ler)
- ✅ Arama kutusu ⇄ filtre paneli iki yönlü senkron
- ✅ Sanal kaydırmalı sonuç tablosu, kelime vurgulama, grup başlıkları
- ✅ Detay paneli: bilgiler, içeren branch'ler, değişen dosyalar, renkli diff (arka planda yüklenir)
- ✅ Klasörde, terminalde ve editörde açma; hash ve mesaj kopyalama; sağ tık menüsü
- ✅ Arka planda indeksleme, ilerleme çubuğu, iptal
- ✅ Güncelleme raporu (başarılı, değişmeyen, hata, bulunamayan, fetch sorunları)
- ✅ Ayarlar, Repolar, Kayıtlı aramalar, İstatistikler pencereleri
- ✅ Son aramalar
- ✅ Açılışta, zamanlanmış ve dosya sistemi izleyerek otomatik güncelleme
- ✅ Açık, koyu ve sistem teması
- ✅ Türkçe ve İngilizce arayüz
- ✅ Klavye kısayolları ve sorgu sözdizimi yardımı
- ✅ İlk açılış karşılama ekranı

## 4. Paketleme ve dağıtım

- ✅ Taşınabilir mod (`comitra-portable.txt`, `--portable`, `COMITRA_HOME`)
- ✅ PyInstaller spec (GUI + CLI, gereksiz Qt modülleri çıkarıldı)
- ✅ Windows: Inno Setup ile kullanıcı bazlı kurulum (yönetici izni gerekmez) + taşınabilir zip
- ✅ macOS: `.app`, `.dmg`, taşınabilir zip, ad-hoc imza
- ✅ Linux: AppImage + taşınabilir tar.gz + `install.sh` (menü kısayolu)
- ✅ Uygulama ikonu (SVG → PNG/ICO/ICNS)
- ✅ GitHub Actions: 3 işletim sistemi × 2 Python sürümünde test ve paket üretimi
- ✅ Tag ile otomatik GitHub Release

## 5. Kalite

- ✅ Birim testleri: normalizasyon, sorgu dili
- ✅ Gerçek git repolarıyla entegrasyon testleri: fast-forward merge, force-push, gc, worktree, bare, taşınan repo, fetch başarı ve hata, dosya, saat ve gün filtreleri
- ✅ Ekransız arayüz duman testi
- ✅ 100 bin commit ile performans ölçümü (bkz. `docs/DESIGN.md`)

## 6. Sonraki sürümler

- 🔜 Kod imzalama: Windows Authenticode ve Apple Developer ID + notarization (sertifika gerektirir)
- 🔜 Diff içeriğinde arama (isteğe bağlı; ayrı bir FTS tablosu ve boyut sınırıyla)
- 🔜 Bulanık (fuzzy) arama ve "bunu mu demek istediniz?" önerileri
- 🔜 Kelime içi arama için isteğe bağlı trigram indeks
- 💡 Yazar kimliklerini elle birleştirme (aynı kişinin farklı e-postaları, `.mailmap` dışı)
- 💡 İstatistik ekranına grafikler
- 💡 Sonuçlardan tek tıkla `git show` / `git checkout` (onaylı)
- 💡 Linux için `.deb` / `.rpm` paketleri, Windows için winget, macOS için Homebrew cask
- 💡 Sorgu kutusunda sözdizimi renklendirme ve filtre otomatik tamamlama
