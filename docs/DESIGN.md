# Comitra – Tasarım Belgesi

Bu belge, ilk fikir dosyasındaki kırılgan noktaların nasıl yeniden tasarlandığını ve
uygulamanın bugünkü mimarisini anlatır. Kodla birebir uyumludur. Bir karar
değişirse önce bu belge güncellenmelidir.

## 1. Mimari

```
                ┌──────────── comitra/ui (PySide6) ────────────┐
                │ MainWindow · FilterPanel · ResultsModel       │
                │ DetailPanel · Dialogs · Workers (QThread)     │
                └───────────────┬───────────────────────────────┘
                                │ (yalnızca core'u çağırır)
┌──────────────────────── comitra/core (Qt'den bağımsız) ───────────────────────┐
│ scanner   → klasörleri gezer, repoları bulur (worktree/submodule/bare)         │
│ gitcmd    → tüm git çağrıları: UTF-8, istem yok, kilit yok, zaman aşımı        │
│ gitrepo   → ref listesi, log ayrıştırma, rev-list, diff                        │
│ fetcher   → isteğe bağlı güvenli `git fetch`                                   │
│ indexer   → ref tabanlı artımlı indeksleme, paralel işçiler, tek yazıcı        │
│ db        → SQLite şeması, WAL, migration (PRAGMA user_version)                │
│ query     → sorgu dili ayrıştırıcı ⇄ Query nesnesi (iki yönlü)                 │
│ search    → Query → SQL, branch çözümleme, sıralama, gruplama                  │
│ textnorm  → Türkçe/aksan normalizasyonu, vurgulama                             │
│ stats, export, service                                                         │
└────────────────────────────────────────────────────────────────────────────────┘
comitra/cli.py → aynı core ile komut satırı arayüzü
```

Çekirdekte Qt'ye bağımlılık yoktur. Bu sayede CLI, testler ve arayüz aynı kodu kullanır.

## 2. Kırılgan noktalar ve çözümleri

### 2.1 Branch üyeliği (en kritik sorun)

**Sorun:** `commit_branches(commit_id, branch_name)` tablosu, bir commit'i ondan türeyen
*her* branch için ayrı satır olarak saklar. 500 bin commit ve 30 branch ≈ 15 milyon satır
eder. Daha kötüsü: fast-forward merge'de yeni commit oluşmaz ama `main` artık feature
commit'lerini de içerir. `rev-list --all --not <eski uçlar>` bu değişikliği göremediği
için tablo sessizce eskir.

**Çözüm:**

- Commit başına branch listesi **saklanmaz**.
- `refs` tablosu her reponun izlenen ref'lerini ve uç commit'lerini tutar.
- Her commit, ilk bulunduğu ref'i (`first_ref`, `git log --source`) gösterim için saklar.
- `branch:` filtresi sorgu anında çözülür: eşleşen ref'lerin uçlarından `git rev-list`
  çalıştırılır ve sonuç `(repo, uç commit'ler)` anahtarıyla önbelleğe alınır. Branch
  ilerlediğinde anahtar değiştiği için önbellek kendiliğinden geçersizleşir. 100 bin
  commit'lik repoda soğuk önbellekle ~1 sn, sıcak önbellekle milisaniyeler sürer.
- Repo klasörü erişilemezse (ör. disk takılı değilse) `first_ref` ile yaklaşık sonuç verilir
  ve kullanıcı uyarılır.
- Detay panelindeki "İçeren branch'ler" bilgisi `git for-each-ref --contains` ile anlık alınır.

### 2.2 Artımlı güncelleme ve kaybolan commit'ler

Güncelleme tarihe göre değil, ref'lere göre yapılır:

1. Ref'ler okunur (yerel branch, uzak branch, tag, detached HEAD). Parmak izi
   değişmemişse repo hiç taranmaz.
2. `eski` = saklı uçlardan hâlâ var olanlar, `yeni` = güncel uçlar.
3. Yeni commit'ler: `git log yeni --not eski`. Tarihi ne olursa olsun daha önce
   görülmemiş her commit gelir.
4. Erişilemez hale gelenler (force-push, rebase, silinen branch):
   `git rev-list eski --not yeni` → `reachable = 0` olarak işaretlenir, **silinmez**.
5. Saklı uçlardan biri `git gc` ile silinmişse 4. adım yapılamaz. Bu durumda tam
   erişilebilirlik taraması yapılır.
6. Erişilemez bir commit'e tekrar bir branch işaret ederse yeniden `reachable = 1` olur.

Erişilemez commit'ler varsayılan olarak aramada gizlidir.
`unreachable:include|only` filtresiyle veya ayarlardan gösterilebilir. "Saklama"
seçeneği kapatılırsa bu commit'ler silinir.

### 2.3 Türkçe tam metin arama

FTS5'in `unicode61` tokenizer'ı I/ı/İ/i dönüşümünü Türkçeye uygun yapmaz ve "odeme" ile
"ödeme"yi eşleştirmez. Çözüm:

- Metin indekse girmeden önce `textnorm.normalize` ile normalize edilir: küçük harf,
  I/ı/İ/i → `i`, aksanlar kaldırılır (ö→o, ş→s, ç→c, ğ→g, ü→u, ß→s…).
- Normalizasyon **uzunluğu korur** (her karakter tek karaktere dönüşür). Bu sayede eşleşme
  konumları normalize metinde bulunup orijinal metin üzerinde vurgulanabilir.
- Sorgu terimleri de aynı fonksiyondan geçer, iki taraf hep tutarlıdır.
- Tokenizer: `unicode61 remove_diacritics 0 tokenchars '_'`. `snake_case` tek kelime,
  `JIRA-1234` iki kelime (`"jira 1234"` ifadesi olarak aranır).
- Kullanıcı girdisi asla doğrudan FTS5'e verilmez. Her terim tırnaklı ifadeye çevrilir,
  bu yüzden `"`, `*`, `:` gibi karakterler sözdizimi hatası üretemez.
- Dışlama (`-wip`) FTS5'in `NOT` operatörüyle değil, ayrı bir `NOT IN` alt sorgusuyla
  yapılır. Böylece tek başına `-wip` de çalışır.

### 2.4 Tarih, saat ve saat dilimi

- Hem yazım tarihi (author date) hem commit tarihi (committer date) saklanır: UTC epoch
  ve commit'in kendi saat dilimi (dakika). Rebase committer date'i değiştirir. Varsayılan
  filtre ve sıralama yazım tarihine göredir, ayarlardan değiştirilebilir.
- Saat ve haftanın günü **commit'in kendi saat diliminde** hesaplanıp saklanır
  (`author_hour`, `author_wday`…). "22:00–06:00 arası commit'ler", yazan kişinin yerel
  saatine göre çalışır.
- Tarih filtreleri (bugün, son 7 gün, aralık) **kullanıcının** yerel gününe göre hesaplanır.
- `after:` dahil, `before:` hariçtir. Arayüzdeki aralık seçimi her iki ucu da dahil eder.

### 2.5 Repo kimliği

- Yol değişse bile repo tanınır: yeni bulunan bir repo, kaybolmuş bir reponun kök commit'i
  (ve gerekirse remote URL'si) ile eşleşirse kayıt yeni yola taşınır, yeniden indekslenmez.
- Linked worktree'ler ana repo ile aynı ref'leri paylaşır. Bu yüzden ortak git klasörünün
  (`commondir`) gerçek yoluna göre tekilleştirilir.
- Submodule'ler (`.git` dosyası → `.git/modules/x`) ayrı repo olarak indekslenir.
- Bare repolar (`HEAD` + `objects` + `refs`) desteklenir.
- Klasörü silinen repo `missing` olarak işaretlenir, commit'leri aranabilir kalır. Ayarlardaki
  kök klasörlerden çıkarılan repolar `inactive` olur. İkisi de Repolar penceresinden kaldırılabilir.

### 2.6 Yazar kimliği

- `%aN/%aE` kullanılır, yani reponun `.mailmap` dosyası uygulanır.
- `Co-authored-by:` satırları ayrıştırılır. `author:` filtresi yazarı ve ortak yazarları
  birlikte arar (ad veya e-posta, içerir eşleşmesi).

### 2.7 Git çağrılarının güvenliği ve taşınabilirliği

`gitcmd` her çağrıda şunları uygular:

- `-c core.quotepath=off -c i18n.logOutputEncoding=UTF-8`, çıktı `errors="replace"`
  ile çözülür. Windows'ta Türkçe dosya adları ve mesajlar bozulmaz.
- `GIT_TERMINAL_PROMPT=0`, `credential.interactive=never`, `GCM_INTERACTIVE=never`.
  Hiçbir çağrı şifre beklerken takılmaz.
- `GIT_OPTIONAL_LOCKS=0`. Kullanıcının kendi git komutlarıyla `index.lock` için yarışılmaz.
- Windows'ta `CREATE_NO_WINDOW`, diğerlerinde ayrı süreç grubu. Zaman aşımında tüm
  süreç ağacı sonlandırılır.
- Uzun girdiler (ref listeleri, hash'ler) komut satırı yerine `--stdin` ile verilir.
  Windows'un 32K komut satırı sınırına takılmaz.
- Çıktı akış halinde okunur. 1 milyon commit'lik log belleğe toplanmaz.
- `git` bulunamazsa PATH ve bilinen kurulum yerlerine bakılır, yine yoksa anlaşılır bir
  uyarı gösterilir. Ayarlardan elle yol verilebilir.
- PyInstaller ile paketlenen Linux sürümünde `LD_LIBRARY_PATH` git'e ve açılan
  terminal/editöre aktarılmaz.

### 2.8 Fetch

Varsayılan kapalıdır. Açıkken:

- `git fetch --all --no-prune --no-recurse-submodules --no-write-fetch-head`
  (kullanıcının `fetch.prune=true` ayarı da etkisiz kalır).
- SSH için `BatchMode=yes` (kullanıcının kendi `core.sshCommand` ayarı varsa ona dokunulmaz).
- Repo başına zaman aşımı, sınırlı paralel fetch, kilit hatasında bir kez yeniden deneme.
- Hata `auth / network / timeout / lock / error` olarak sınıflandırılır. Tarama yerel
  verilerle devam eder ve sorun özet ekranında gösterilir.

### 2.9 Eşzamanlılık

- İndeksleme `ThreadPoolExecutor` ile paralel çalışır (git alt süreçleri GIL'i tutmaz).
- Tüm yazmalar tek bir `Writer` nesnesinden, kilit altında ve 2000'lik toplu
  transaction'larla yapılır. SQLite WAL modundadır.
- Arayüz: indeksleme `QThread`'de, arama ayrı bir `QThread`'de ve kendi bağlantısıyla çalışır.
  "En yeni istek kazanır" kuralıyla eski arama sonuçları atılır. Diff, içeren branch'ler,
  istatistik ve dışa aktarma `QThreadPool` görevleridir. Arayüz hiç donmaz.

### 2.10 Büyük sonuç listeleri

Arama, eşleşen tüm commit id'lerini sıralı olarak döndürür (en fazla 2 milyon). Satır
sayısı kesindir. Tablo modeli satırları 200'lük bloklar halinde, yalnızca görünür
olduklarında yükler (LRU önbellek). Bu gerçek sanal kaydırmadır. Gruplama aynı id listesi
üzerinde yapılır.

### 2.11 Şema evrimi

`PRAGMA user_version` şema sürümünü tutar. `db.MIGRATIONS` listesine eklenen her adım
açılışta, transaction içinde sırayla uygulanır. Daha yeni bir şemayı eski bir sürüm
açmaya çalışırsa anlaşılır bir hata verir.

## 3. Veritabanı şeması

| Tablo | İçerik |
| --- | --- |
| `repos` | yol, ad, git klasörü, bare mı, kök commit, remote URL, durum, ref parmak izi, commit sayısı |
| `refs` | repo başına izlenen ref'ler ve uç commit'leri |
| `commits` | hash, ebeveynler, yazar/commit eden, iki tarih + saat dilimi + yerel saat/gün, konu, mesaj, `first_ref`, `reachable` |
| `coauthors` | `Co-authored-by` kişileri |
| `paths`, `commit_files` | (isteğe bağlı) değişen dosya yolları; yol sözlüğü sayesinde tekrar yok |
| `commits_fts` | FTS5, normalize mesaj; `rowid = commits.id` |
| `saved_searches`, `recent_searches` | kayıtlı ve son aramalar |

Diff'ler saklanmaz, detay ekranında Git'ten anlık alınır (2 MB sınırı).

## 4. Sorgu dili

`query.parse()` ve `Query.to_string()` birbirinin tersidir (testlerle doğrulanır). Arama
kutusu ile filtre paneli aynı `Query` nesnesini paylaşır:

- Kullanıcı arama kutusuna yazar → ayrıştırılır → panel güncellenir (sinyaller susturulur).
- Kullanıcı panelde değişiklik yapar → `Query` güncellenir → arama kutusu kanonik metne çevrilir.

Türkçe takma adlar desteklenir (`yazar:`, `proje:`, `dal:`, `tarih:bugün`, `gün:cuma`,
`saat:`, `merge:gizle`…). Geçersiz filtreler sessizce yutulmaz, uyarı olarak gösterilir.

## 5. Gizlilik ve çevrimdışı çalışma

- Uygulama hiçbir ağ isteği yapmaz. Tek istisna, kullanıcının açıkça etkinleştirdiği
  `git fetch`'tir; o da kullanıcının kendi git sunucularına gider.
- Telemetri, güncelleme kontrolü veya uzak font/ikon yoktur. Tüm kaynaklar pakettedir.

## 6. Taşınabilir mod

Programın yanında `comitra-portable.txt` dosyası varsa (taşınabilir paketlerde vardır) ya da
`--portable` / `COMITRA_HOME` kullanılırsa ayarlar ve veritabanı programın yanındaki
`comitra-data` klasöründe tutulur. Aksi halde platformdirs ile işletim sistemine uygun
kullanıcı klasörleri kullanılır.

## 7. Ölçümler (geliştirme makinesi, Linux)

| İşlem | Süre |
| --- | --- |
| 100.000 commit'lik repoyu ilk indeksleme | 4,6 sn |
| Değişmemiş repoyu güncelleme | < 0,05 sn |
| Tam metin arama (100 bin commit) | ~30 ms |
| Yazar + tarih + dışlama araması | ~5 ms |
| `branch:` filtresi, soğuk önbellek | ~1,1 sn |
| Veritabanı boyutu (100 bin commit) | ~55 MB |
