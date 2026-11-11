<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/energy_metrics_eon/brand/dark_logo.png">
    <img alt="Energy Monitoring for E.ON Hungary" src="custom_components/energy_metrics_eon/brand/logo.png" width="480">
  </picture>
</p>

# Energy Monitoring for E.ON Hungary

Home Assistant integráció, amely az **E.ON** távleolvasási portál órás **fogyasztási és
visszatáplálási** adatait tölti be a hosszú távú statisztikákba, az **Energia irányítópulthoz**.
A portál ütemezett e-mail exportját dolgozza fel. Nincs scraping, nincs IMAP, nincs nyitott port.

[![HACS validation](https://github.com/baranyit/energy-metrics-eon/actions/workflows/hacs.yml/badge.svg)](https://github.com/baranyit/energy-metrics-eon/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/baranyit/energy-metrics-eon/actions/workflows/hassfest.yml/badge.svg)](https://github.com/baranyit/energy-metrics-eon/actions/workflows/hassfest.yml)

🇬🇧 [English version](README.md)

> **Állapot: béta (0.1.0).** Az adatok jellemzően egynapos késéssel érkeznek, mert a portál
> naponta egyszer küldi az exportot. Ez egy nem hivatalos projekt, nem kapcsolódik az E.ON-hoz,
> és az E.ON nem támogatja. Csak saját felelősségre használd.

## Mit tud?

Egy beállított bejegyzés egy mérési pontot (POD) kezel. Mindegyikhez ad:

- két **hosszú távú statisztikát** az Energia irányítópulthoz: `energy_metrics_eon:<név>_import`
  (hálózati fogyasztás) és `energy_metrics_eon:<név>_export` (visszatáplálás), órás kWh-ban,
- négy **diagnosztikai érzékelőt**: utolsó feldolgozott e-mail, következő e-mail ellenőrzés,
  legfrissebb fogyasztási adat és legfrissebb visszatáplálási adat,
- két **műveletet**: `energy_metrics_eon.import_file` a korábbi adatok visszatöltéséhez egy letöltött
  fájlból, és `energy_metrics_eon.check_now` az azonnali e-mail ellenőrzéshez.

A portál negyedórás értékeit órásra összegzi, és azok mindig a helyes órákhoz kerülnek, akkor is,
ha késve vagy többször érkeznek.

## Miért e-mailen keresztül?

A portál
([e-portal.eon-hungaria.com/w1000/tavleolv](https://e-portal.eon-hungaria.com/w1000/tavleolv))
teljes egészében Cloudflare bot-védelem mögött van, a bejelentkezés pedig reCAPTCHA-t használ,
ezért a Home Assistant nem tud közvetlenül belépni és lekérdezni. A portál saját ütemezett
exportja viszont naponta elküldi az adatokat e-mailben, ezt dolgozza fel az integráció:

```
E.ON portál ──napi e-mail──▶ Gmail ◀────── lekérdezés ─────── Home Assistant
                              (Apps Script)                   (statisztika import)
```

- **A Home Assistant zárt marad.** Csak kimenő kéréseket indít, nem kell kinyitni az internet
  felé.
- **A Gmail zárt marad.** A saját Google-fiókodban futó kis Apps Script csak a megadott tárgyú
  leveleket adja ki, és csak a titkos tokennel. Csak olvas.
- **Kevés lekérdezés.** Minden levél után 22 óra szünet következik, utána óránként ellenőriz
  (lásd: [mikor ellenőrzi a leveleket](#mikor-ellenőrzi-a-leveleket)).

## Telepítés

HACS-ból (egyéni tárolóként) vagy kézi másolással:

1. HACS → ⋮ → Egyéni tárolók → add hozzá a `https://github.com/baranyit/energy-metrics-eon`
   címet *Integráció* típussal, telepítsd az **Energy Monitoring for E.ON Hungary** integrációt,
   majd indítsd újra a Home Assistantot.
   Kézzel: másold a `custom_components/energy_metrics_eon` mappát a Home Assistant `custom_components`
   könyvtárába.

   [![HACS tároló megnyitása](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=baranyit&repository=energy-metrics-eon&category=integration)
2. Beállítások → Eszközök és szolgáltatások → Integráció hozzáadása →
   **Energy Monitoring for E.ON Hungary** (az alábbi [beállítási](#beállítás) lépések után,
   mert azokból kapod meg a kért URL-t és tokent).

Home Assistant 2024.12 vagy újabb kell hozzá, valamint az `openpyxl` (automatikusan települ).

## Beállítás

### 1. Ütemezett export a portálon

1. Lépj be a portálra, a Távleolvasás oldalon válaszd ki a mérési pontot.
2. Állíts be ütemezett exportot: **napi** gyakoriság, **negyedórás** (napon belüli) felbontás,
   a fogyasztás és a visszatáplálás mérőváltozóival (jellemzően `+A` és `-A`), **XLSX** (vagy
   CSV) formátumban, a Gmail címedre.
3. A levél tárgya legyen pontosan: `energy-metrics-eon` (ha mást adsz meg, írd át a `QUERY` sort
   a scriptben).

### 2. Apps Script a Gmail fiókodban

1. Nyisd meg a [script.google.com](https://script.google.com) oldalt, **Új projekt**.
2. Másold be az [apps_script/Code.gs](apps_script/Code.gs) tartalmát, mentsd el.
3. Válaszd ki a `setup` függvényt, és futtasd. Engedélyezd a Gmail-hozzáférést, majd a
   **Végrehajtási naplóból** másold ki a tokent. A Google figyelmeztet, hogy az alkalmazás nincs
   ellenőrizve: ez a saját scripted. Kattints a **Speciális → Tovább … (nem biztonságos)**, majd
   az **Engedélyezés** gombra.
4. **Telepítés → Új telepítés → Webalkalmazás**: futtatás *saját nevemben*, hozzáférés: *Bárki*.
   Másold ki a `…/exec` végű URL-t.

A `rotateToken` függvény futtatásával a token bármikor lecserélhető. Az engedélykérés a teljes
Gmail-hozzáférést említi, mert az Apps Script `GmailApp` szolgáltatásának nincs szűkebb
jogosultsága.

### 3. Az integráció

Add hozzá az integrációt, és add meg az `…/exec` URL-t, a tokent és az oszlopneveket. A beállítás
egyetlen kéréssel ellenőrzi az URL-t és a tokent.

### 4. Energia irányítópult

Beállítások → Irányítópultok → Energia: a hálózati fogyasztáshoz válaszd az
`energy_metrics_eon:<név>_import`, a visszatápláláshoz az `energy_metrics_eon:<név>_export` statisztikát. Ezek az
első sikeres import után jelennek meg.

## Beállítási lehetőségek

Mindegyiket a beállításkor kell megadni, és a név kivételével később az *Újrakonfigurálás*
menüpontban módosíthatók.

| Beállítás | Alapérték | Jelentés |
|---|---|---|
| Név | `E.ON` | Ebből képződik a statisztika azonosítója. Később nem módosítható. |
| Apps Script webalkalmazás URL | nincs | A közzétett script `…/exec` végű címe. |
| Token | nincs | A script `setup` függvénye által kiírt token. |
| Fogyasztás oszlop neve | `+A` | Az export fejlécében szereplő mérőváltozó. Üresen hagyható. |
| Visszatáplálás oszlop neve | `-A` | Üresen hagyható, ha nincs visszatáplálás. A két oszlop közül legalább az egyik kell. |
| Mérési pont (POD) azonosító | üres | Csak akkor kell, ha az export több mérési pontot tartalmaz (pl. `HU000…`). |
| Az időbélyeg az intervallum végét jelöli | ki | Kapcsold be, ha az első napi sor `00:15`, különben az adatok negyedórával elcsúsznak. |

### Mikor ellenőrzi a leveleket?

Az E.ON naponta egyszer küldi az exportot, ezért az integráció nem kérdez feleslegesen:

- Az utolsó feldolgozott levél érkezése után **22 óráig nem ellenőriz**.
- Utána **óránként** kérdezi le az Apps Scriptet, amíg meg nem jön a következő levél, majd újra
  22 óra szünet következik. A napi levél így legfeljebb egy órán belül bekerül, és naponta csak
  néhány lekérdezés történik.
- A 2 órás tartalék arra jó, hogy a levél kicsit korábban is érkezhet, mint előző nap.
- Az első induláskor, és amíg még egy levelet sem dolgozott fel, óránként ellenőriz; az első
  futáskor az összes korábbi, a keresésre illeszkedő levelet feldolgozza.
- Ha egy levelet nem tud értelmezni, a szünetet figyelmen kívül hagyva óránként újrapróbálja,
  amíg a hibát el nem hárítod.

A **Következő e-mail ellenőrzés** érzékelő mutatja, mikor kérdez legközelebb. Azonnali
ellenőrzéshez (pl. ha a levél a szokásosnál korábban jött):

```yaml
action: energy_metrics_eon.check_now
```

### Korábbi adatok visszatöltése

A portálról kézzel letöltött CSV/XLSX fájl is importálható. Másold a fájlt a Home Assistant egy
engedélyezett könyvtárába (pl. `/config/eon/`), majd hívd meg:

```yaml
action: energy_metrics_eon.import_file
data:
  path: /config/eon/export.xlsx
```

A válaszban látszik, milyen fájltípust és mérőváltozókat talált, és hány órát írt be. Ugyanaz az
időszak többször is importálható, az értékek felülíródnak, nem duplázódnak.

## Hogyan dolgozza fel az adatokat?

- **Órás kWh.** A negyedórás értékeket órásra összegzi. A Wh és MWh értékeket kWh-ra váltja.
- **Magyar helyi idő.** Az időbélyegeket magyar helyi időként értelmezi, az őszi óraátállítás
  ismétlődő óráját is kezeli.
- **Kétféle fájlt** ismer fel automatikusan: az ütemezett e-mail exportot (pl. `adatok.xlsx`:
  mérési pontonként egy munkalap, soronként Pod / Időbélyeg / Változó / Érték / Mértékegység) és
  a portálról kézzel letöltött táblát (`MertErtekek_*.xlsx`: `Dátum/Idő`, `+A`, `-A` oszlopok).
- **Negyedórás szintű összefésülés.** Egy negyedóra új értéke felülírja a korábbit, a fájlból
  hiányzó negyedórák pedig megtartják a már tárolt értéküket. Az órás értékeket mindig ebből
  számolja újra, így az átfedő vagy ismételten elküldött adatok nem adódnak össze, és egy hiányos
  fájl nem csökkentheti egy már teljes óra fogyasztását.
- **A még nem teljes óra** (pl. a nap végén levágott export) a meglévő negyedórák összegével
  kerül be, és a következő exporttal kiegészül.

## Ismert korlátok

- Az adatok nem élők: a portál napi levelét követik, jellemzően egynapos késéssel.
- Postafiókként csak a Gmail használható, az Apps Scripten keresztül.
- Egy bejegyzés egy mérési pontot kezel. Ha az export több mérési pontot tartalmaz, add meg a POD
  azonosítót; több mérési ponthoz vedd fel az integrációt többször.
- A felület a Home Assistant nyelvét követi (angol és magyar), de a statisztikák neve angol
  (pl. „E.ON consumption”).
- A bejegyzés neve később nem módosítható, mert ebből képződik a statisztika azonosítója.

## Hibaelhárítás

- **Nem kerül be adat.** Nézd meg az **Utolsó feldolgozott e-mail** és a **Következő e-mail
  ellenőrzés** érzékelőt, majd futtasd az `energy_metrics_eon.check_now` műveletet. Ellenőrizd, hogy a
  levél tárgya egyezik-e a script `QUERY` sorával.
- **Egy csatolmányt nem tud értelmezni.** A feldolgozás megáll, és a hibaüzenet kiírja a fájlban
  talált mérőváltozókat. Az oszlopnevek javítása után onnan folytatja.
- **A script elutasítja a tokent.** A Home Assistant bekéri az újat (újrahitelesítés); új tokent
  a script `rotateToken` függvénye készít.
- **A script nem érhető el.** Ellenőrizd, hogy webalkalmazásként, *Bárki* hozzáféréssel van-e
  közzétéve, és hogy az URL `…/exec` végű-e.
- **Az értékek negyedórával elcsúsznak.** Kapcsold át *Az időbélyeg az intervallum végét jelöli*
  beállítást az *Újrakonfigurálás* menüpontban.

## Fejlesztés

Az értelmező, az összefésülés és az ütemezés Home Assistant nélkül tesztelhető:

```bash
python3 -m unittest discover -s tests -v
```

A portál belső API-ja (referenciaként, böngészőn kívülről nem érhető el):
`/sap/opu/odata/sap/ZWB5_ONLINE_SRV/Login` (belépés, reCAPTCHA tokennel) és
`/sap/opu/odata/sap/ZWB5_W1000/MeasData(...)` (idősorok, `Bearer <guid>`).

## Licenc

MIT, lásd: [LICENSE](LICENSE).
