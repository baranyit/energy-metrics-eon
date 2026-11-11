# E.ON W1000 → Home Assistant Energy dashboard

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/baranyit/eon-energy-metrics/actions/workflows/validate.yml/badge.svg)](https://github.com/baranyit/eon-energy-metrics/actions/workflows/validate.yml)

> *English:* Home Assistant integration that imports hourly electricity
> consumption and feed-in from E.ON Hungary's W1000 smart meter portal via its
> scheduled e-mail export (Gmail + Google Apps Script), for the Energy dashboard.

Home Assistant custom integration, ami az E.ON távleolvasási portál
([e-portal.eon-hungaria.com/w1000/tavleolv](https://e-portal.eon-hungaria.com/w1000/tavleolv))
**ütemezett e-mail exportjából** tölti be az órás fogyasztási és visszatáplálási
adatokat a Home Assistant statisztikáiba.

## Miért e-mailen keresztül?

A portál teljes egészében Cloudflare bot-védelem mögött van, a bejelentkezés
pedig reCAPTCHA-t használ, ezért a Home Assistant nem tud közvetlenül belépni és
lekérdezni. A portál saját ütemezett exportja viszont naponta elküldi az adatokat
e-mailben, ezt dolgozza fel az integráció:

```
E.ON portál ──napi e-mail──▶ Gmail ◀──óránkénti lekérdezés── Home Assistant
                              (Apps Script)                   (statisztika import)
```

A Home Assistantot nem kell kinyitni az internet felé, és IMAP sem kell.
Az adatok jellemzően egynapos késéssel érkeznek, de a helyes órákhoz kerülnek.

## Telepítés

### 1. Ütemezett export a portálon

1. Lépj be a portálra, a Távleolvasás oldalon válaszd ki a mérési pontot.
2. Állíts be ütemezett exportot: **napi** gyakoriság, **negyedórás** (napon
   belüli) felbontás, a fogyasztás és a visszatáplálás mérőváltozóival
   (jellemzően `+A` és `-A`), **XLSX** (vagy CSV) formátumban, a Gmail címedre.
3. A levél tárgya legyen pontosan: `eon-energy-metrics`
   (ha mást adsz meg, írd át a `QUERY` sort a scriptben).

### 2. Apps Script a Gmail fiókodban

1. Nyisd meg a [script.google.com](https://script.google.com) oldalt, **Új projekt**.
2. Másold be az [apps_script/Code.gs](apps_script/Code.gs) tartalmát, mentsd el.
3. Válaszd ki a `setup` függvényt, és futtasd. Engedélyezd a Gmail-hozzáférést,
   majd a **Végrehajtási naplóból** másold ki a tokent.
4. **Telepítés → Új telepítés → Webalkalmazás**:
   futtatás *saját nevemben*, hozzáférés: *Bárki*. Másold ki a `…/exec` végű URL-t.

A script csak olvas, és csak a megadott tárgyú leveleket adja ki, kizárólag a
tokennel. A `rotateToken` függvény futtatásával a token bármikor lecserélhető.
Az engedélykérés a teljes Gmail-hozzáférést említi, mert az Apps Script
`GmailApp` szolgáltatásának nincs szűkebb jogosultsága.

### 3. Az integráció

1. Telepítsd HACS-ból: **HACS → ⋮ → Egyéni tárolók**, tároló:
   `https://github.com/baranyit/eon-energy-metrics`, típus: **Integráció**.
   Ezután keresd meg az „E.ON W1000” integrációt, töltsd le, és indítsd újra
   a Home Assistantot.

   [![HACS tároló megnyitása](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=baranyit&repository=eon-energy-metrics&category=integration)

   Kézi telepítés: másold a `custom_components/eon_w1000` mappát a Home
   Assistant `config/custom_components` könyvtárába.
2. **Beállítások → Eszközök és szolgáltatások → Integráció hozzáadása → E.ON W1000**.
3. Add meg az `…/exec` URL-t, a tokent és az oszlopneveket.

### 4. Energy dashboard

**Beállítások → Irányítópultok → Energia**: a hálózati fogyasztáshoz válaszd az
`eon_w1000:<név>_import`, a visszatápláláshoz az `eon_w1000:<név>_export`
statisztikát. Ezek az első sikeres import után jelennek meg.

## Korábbi adatok visszatöltése

A portálról kézzel letöltött CSV/XLSX fájl is importálható. Másold a fájlt a
Home Assistant egy engedélyezett könyvtárába (pl. `/config/eon/`), majd hívd meg:

```yaml
action: eon_w1000.import_file
data:
  path: /config/eon/export.csv
```

A válaszban látszik, milyen fájltípust és mérőváltozókat talált, és hány órát
írt be. Ugyanaz az időszak többször is importálható, az értékek felülíródnak,
nem duplázódnak.

## Működés és korlátok

- Az integráció óránként kérdezi le az új leveleket; az első futáskor az összes
  korábbi, a keresésre illeszkedő levelet feldolgozza.
- A negyedórás értékeket órásra összegzi (kWh). Az időbélyegeket magyar helyi
  időként értelmezi, az őszi óraátállítás ismétlődő óráját is kezeli.
- Ha az időbélyeg az intervallum **végét** jelöli (az első napi sor `00:15`),
  kapcsold be a megfelelő beállítást, különben az adatok negyedórával elcsúsznak.
- Kétféle fájlt ismer fel automatikusan: az ütemezett e-mail exportot
  (pl. `adatok.xlsx`: mérési pontonként egy munkalap, soronként
  Pod / Időbélyeg / Változó / Érték / Mértékegység) és a portálról kézzel
  letöltött táblát (`MertErtekek_*.xlsx`: `Dátum/Idő`, `+A`, `-A` oszlopok).
  A Wh és MWh értékeket kWh-ra váltja.
- Ha egy csatolmányt nem tud értelmezni, megáll, és a hibaüzenetben kiírja a
  fájlban talált mérőváltozókat. A beállítás javítása után onnan folytatja.
- Egy beállított bejegyzés egy mérési pontot kezel. Ha az export több mérési
  pontot tartalmaz, a beállításoknál add meg a POD azonosítót; több mérési
  ponthoz vedd fel az integrációt többször.
- Az adatokat negyedórás szinten fésüli össze: egy negyedóra új értéke
  felülírja a korábbit, a fájlból hiányzó negyedórák pedig megtartják a már
  tárolt értéküket. Az órás értékeket mindig ebből számolja újra, így az
  átfedő vagy ismételten elküldött adatok nem adódnak össze, és egy hiányos
  fájl nem csökkentheti egy már teljes óra fogyasztását.
- Egy még nem teljes óra (pl. a nap végén levágott export) a meglévő
  negyedórák összegével kerül be, és a következő exporttal kiegészül.
- Három diagnosztikai érzékelő mutatja az utolsó feldolgozott e-mail és a
  legfrissebb importált adat idejét.

## Fejlesztés

Az értelmező és az összefésülés Home Assistant nélkül tesztelhető:

```bash
python3 -m unittest discover -s tests -v
```

A portál belső API-ja (referenciaként, böngészőn kívülről nem érhető el):
`/sap/opu/odata/sap/ZWB5_ONLINE_SRV/Login` (belépés, reCAPTCHA tokennel) és
`/sap/opu/odata/sap/ZWB5_W1000/MeasData(...)` (idősorok, `Bearer <guid>`).

## Licenc

MIT, lásd: [LICENSE](LICENSE). A projekt nem kapcsolódik az E.ON-hoz.
