# ELi Piiririski Profiiler

**ELi Piiririski Profiiler** on spetsialiseeritud luuresüsteem, mis jälgib ja prognoosib varjupaigataotluste survet ELi välispiiridel. Süsteem kasutab Eurostati ajaloolisi andmeid, et arvutada reaalajas „riskiskoorid“ ning prognoosida tulevasi trende masinõppe abil.

![EU Border Risk Profiler Dashboard](dashboard_preview.png)

## Põhifunktsioonid

* **Arenenud riskihindamine**: Kasutab logaritmilist globaalse normaliseerimise valemit, et tuvastada kõrge riskiga tsoonid ilma ajalooliste äärmusjuhtumite (nt 2015. aasta kriis) moonutava mõjuta.  
  * `Risk = (log(Volume) / log(Global_Max)) * (1 + Trend_Variation)`

* **Tark andmetöötlus**: Käsitleb automaatselt andmeviivitusi, tagades, et soojuskaart kajastab alati *uusimaid kehtivaid* riiklikke andmeid ning väldib eksitavaid „nullriski“ alasid raportite hilinemise tõttu.

* **Prognoosimudelid**: Treenib iga ELi 27 liikmesriigi jaoks kergekaalulised Random Forest’i regressioonimudelid, et prognoosida survet 3 kuud ette.

* **Moodne juhtimisdashboard**: Streamliti baasil loodud „Situation Room“ stiilis liides, mille funktsioonide hulka kuuluvad dünaamilised soojuskaardid, riskihinnangute edetabelid ja riigipõhised detailvaated.

## Süsteemi arhitektuur

Lahendus järgib Docker Compose’i abil orkestreeritud mikroteenuste arhitektuuri:

1. **Data Harvester** (`data_harvester`):  
   * **Roll**: Autonoomne agent, mis küsib Eurostati Bulk API-t (`migr_asyappctzm`) iga päev kell 02:00.  
   * **Töömehhanism**: Teostab diferentsiaaluuendusi, töötleb TSV-vooge ja tegeleb andmepuhastusega.

2. **Risk Predictor** (`risk_predictor`):  
   * **Roll**: Luuremootor, mis käivitatakse iga päev kell 03:00.  
   * **Loogika**:  
       * Laadib puhastatud andmed PostgreSQL-ist.  
       * Arvutab „riskiskoori“ (maht × trend).  
       * **Automaatne ümberõpe**: Kontrollib uusi andmeid ja treenib riigipõhiseid mudeleid uuesti vastavalt vajadusele.  
       * Genereerib prognoosid +1, +2 ja +3 kuu jaoks.

3. **API Service** (`api_service`): FastAPI-põhine backend.

4. **Dashboard** (`dashboard`): Streamliti põhine visualisatsioonikiht.

5. **PostgreSQL** (`db`): Keskne andmepüsivuse kiht.

## Süsteeminõuded

Projekt on optimeeritud efektiivsuseks ega vaja tugevat riistvara ega GPU-sid.

* **CPU**: 1 vCPU (soovitatav 2)  
* **RAM**: vähemalt 1 GB (soovitatav 2 GB)  
* **GPU**: Pole vajalik  
* **Kettaruum**: 5 GB

## Kiirstart

1. **Eeldused**: Docker & Docker Compose  
2. **Konfiguratsioon**: Määra `.env` failis andmebaasi seadistused  
3. **Käivitus**:
```
docker-compose up --build -d
```
4. **Ligipääs**:  
   * Dashboard: `http://localhost:8501`  
   * API dokumentatsioon: `http://localhost:8000/docs`

## Metoodika

### Riskivalem
Riskiskoor (0–100) põhineb:

* **Mahukomponendil** – logaritmiliselt normaliseeritud ELi ajaloo maksimumi suhtes  
* **Trendikomponendil** – kuust-kuusse muutuse kiirenemine/aeglustumine

### Masinõpe
* **Mudelitüüp**: Random Forest Regressor  
* **Üks mudel iga riigi kohta**  
* **Automaattreenimine**, kui tuvastatakse uusi andmeid

## Projekti struktuur

```
eu-border-risk-profiler/
├── api_service/
├── dashboard/
├── data_harvester/
├── risk_predictor/
├── docker-compose.yml
└── OPERATIONS_GUIDE.md
```

## Litsents

MIT License  
© 2025
