# ELi Piiririski Profiiler

**ELi Piiririski Profiiler** on spetsialiseeritud luuresüsteem, mis jälgib ja prognoosib varjupaigataotluste survet ELi välispiiridel. Süsteem kasutab Eurostati ajaloolisi andmeid, et arvutada reaalajas „riskiskoorid“ ning prognoosida tulevasi trende masinõppe abil.

🌐 **Live demo** — [risk-profiler.super-h.fr](https://risk-profiler.super-h.fr/)

![EU Border Risk Profiler Dashboard](dashboard_preview.png)

## Põhifunktsioonid

* **Arenenud riskihindamine**: Kasutab logaritmilist globaalse normaliseerimise valemit, et tuvastada kõrge riskiga tsoonid ilma ajalooliste äärmusjuhtumite (nt 2015. aasta kriis) moonutava mõjuta.
  * `Risk = (log(Volume) / log(Global_Max)) * (1 + Trend_Variation)`

* **Tark andmetöötlus**: Käsitleb automaatselt andmeviivitusi, tagades, et soojuskaart kajastab alati *uusimaid kehtivaid* riiklikke andmeid ning väldib eksitavaid „nullriski“ alasid raportite hilinemise tõttu.

* **Prognoosimudelid**: Treenib iga ELi 27 liikmesriigi jaoks kergekaalulised Random Forest’i regressioonimudelid, et prognoosida survet 3 kuud ette. Iga prognoos sisaldab ka P10/P90 usaldusvahemikku, mis tuletatakse mudeli sisemiste otsustuspuude jaotusest.

* **Detailvaade kodakondsuste lõikes**: Iga riigi vaatel kuvatakse N enim taotlejate päritoluriiki ajateljel (N on valitav vahemikus 3-10).

* **Mitmekeelne kasutajaliides**: Saadaval inglise, eesti ja prantsuse keeles, riikide nimed on lokaliseeritud. Keelevalija on lehe paremas ülaosas või URL-i parameetris `?lang=`.

* **Moodne juhtimisdashboard**: Streamliti baasil loodud „Situation Room“ stiilis liides, mille funktsioonide hulka kuuluvad dünaamilised soojuskaardid, riskihinnangute edetabelid ja riigipõhised detailvaated.

## Süsteemi arhitektuur

Lahendus järgib Docker Compose’i abil orkestreeritud mikroteenuste arhitektuuri:

1. **Data Harvester** (`data_harvester`):
   * **Roll**: Autonoomne agent, mis küsib Eurostati Bulk API-t (`migr_asyappctzm`) iga päev kell 02:00.
   * **Töömehhanism**: Laadib uusi andmeid ainult siis, kui Eurostati `Last-Modified` on muutunud, töötleb TSV-vooge tükkidena ja kasutab atomaarset staging-tabeli vahetust, et `asylum_data` ei jääks kunagi pooleli.

2. **Risk Predictor** (`risk_predictor`):
   * **Roll**: Luuremootor, mis käivitatakse iga päev kell 03:00.
   * **Loogika**:
       * Laadib puhastatud andmed PostgreSQL-ist.
       * Arvutab „riskiskoori“ (maht × trend).
       * **Automaatne ümberõpe**: Iga riigi kohta arvutatakse andmete SHA-256 allkiri; mudel treenitakse uuesti ainult siis, kui allkiri on muutunud.
       * **Aus hindamine**: Kasutab kronoloogilist train/test-jaotust ja annab MAE viimase ~20% andmete põhjal, mida mudel ei ole näinud.
       * Genereerib prognoosid +1, +2 ja +3 kuu jaoks.

3. **API Service** (`api_service`): FastAPI-põhine backend, mis jagab koos dashboard’iga sama image’it ja `api_service` paketti.

4. **Dashboard**: Streamliti põhine visualisatsioonikiht, mis küsib kõik andmed API kaudu.

5. **PostgreSQL** (`db`): Keskne andmepüsivuse kiht, mille port on hostis seotud ainult `127.0.0.1`-iga.

## Süsteeminõuded

Projekt on optimeeritud efektiivsuseks ega vaja tugevat riistvara ega GPU-sid.

* **CPU**: 1 vCPU (soovitatav 2)
* **RAM**: vähemalt 1 GB (soovitatav 2 GB)
* **GPU**: Pole vajalik (Scikit-learn töötab CPU-l)
* **Kettaruum**: 5 GB (Docker image’id + andmebaasi maht)

## Kiirstart

1. **Eeldused**: Docker & Docker Compose
2. **Konfiguratsioon**: Kopeeri `.env.example` failiks `.env` ja seadista andmebaasi mandaadid
3. **Käivitus**:
   ```bash
   docker-compose up --build -d
   ```
4. **Ligipääs**:
   * Dashboard: `http://localhost:8501`
   * API dokumentatsioon: `http://localhost:8000/docs`

## Metoodika

### Riskivalem
Riskiskoor (0–100) põhineb:

* **Mahukomponendil** – logaritmiliselt normaliseeritud kogu ELi ajaloo maksimumi suhtes (1,3 mln taotlust 2015. aastal). See tagab, et praegune kriis (nt 100k taotlust) registreeritakse „kõrge riskiga“ kategoorias (~85/100), mitte „madala riskiga“ võrreldes lineaarselt minevikuga.
* **Trendikomponendil** – kuust-kuusse muutuse kiirenemine või aeglustumine.

### Masinõpe
* **Mudelitüüp**: Random Forest Regressor (Scikit-learn).
* **Üks mudel iga ELi liikmesriigi kohta**, treenitud kuni 60 kuu ajaloolise andmestiku peal.
* **Treenimisstrateegia**: Süsteem proovib esmalt laadida olemasoleva mudeli (`model_registry` tabelist). Kui igapäevase käivituse ajal tuvastatakse uusi andmeid, käivitatakse ümberõpe automaatselt, et prognoosid püsiksid täpsed.

## Projekti struktuur

```
eu-border-risk-profiler/
├── api_service/      # FastAPI backend + Streamlit dashboard
├── data_harvester/   # Eurostat parser ja laadija (atomaarne staging-vahetus)
├── risk_predictor/   # Mudelite treenimine ja skoorimine (RandomForest, hold-out hindamine)
├── db_init/          # PostgreSQL skeemi initsialiseerimine
├── docs/             # Vormistatud dokumentatsioon (ADR-id, model card, ohumudel)
├── docker-compose.yml
├── DEPLOYMENT_GUIDE.md
├── DOKPLOY_GUIDE.md
└── OPERATIONS_GUIDE.md
```

## Dokumentatsioon

Käitamise ja juurutamise juhendid:

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — juurutus Docker Compose’iga.
- [DOKPLOY_GUIDE.md](DOKPLOY_GUIDE.md) — märkused Dokploy-spetsiifiliste seadete kohta.
- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) — käitamisjuhend.

Tehniline ja juhtimisalane dokumentatsioon kataloogis [`docs/`](docs/):

- [Architecture Decision Records](docs/adr/README.md) — peamised tehnilised valikud, Michael Nygardi ADR-vormingus.
- [Model Card](docs/MODEL_CARD.md) — prognoosimudeli ulatus, hindamismetoodika, kasutusotstarbed ja keelatud kasutused.
- [Data Card](docs/DATA_CARD.md) — lähteandmestiku kirjeldus, viivitused ja revisjonid, mida andmestik *ei ole*.
- [Security posture](docs/SECURITY.md) — STRIDE-ohumudel ja kontrollid.

## Litsents

MIT License
© 2025
