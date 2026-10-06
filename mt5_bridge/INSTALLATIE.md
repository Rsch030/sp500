# MT5-bridge voor Rsch030/sp500 — Windows-VPS + Railway

Status: zes lokale tests geslaagd. De bridge wordt via de browser op branch mt5-bridge-demo geplaatst en als aparte Railway-service ingericht. Een Windows-VPS en de echte MT5-verbinding zijn nog niet getest. Volg de actuele servicegegevens in het begeleidende bericht.

Deze bridge gebruikt de bestaande signal_for/regime_snapshot functies van bot.py met echte broker-M5-koersen. Railway rekent signalen uit; een Windows-worker leest MT5 en verstuurt eventueel demo-orders. Het bestaande SPY-paperdashboard blijft een aparte simulatie en toont geen daadwerkelijke MT5-transacties.

## 1. Windows-VPS klaarzetten vanaf iPhone

Neem een Windows-VPS met Windows Server 2022/2025, 2 vCPU, 4 GB RAM, 40 GB SSD en een Windows-licentie/RDP. Dit zijn praktische startspecificaties, geen providerselectie of prijsopgave. Je bestelt hem zelf; er is hier geen VPS aangeschaft.

Installeer Microsoft Windows App op je iPhone. Kies + > PC toevoegen, vul het IP-adres van je VPS in en de Windows-gebruikersnaam en het Windows-wachtwoord van je provider. Dit zijn andere gegevens dan je FTMO-login. Gebruik bij voorkeur de beveiligde RDP-toegang die je VPS-provider aanbiedt.

## 2. MT5 en Python installeren op de VPS

Open op de VPS de FTMO Client Area > jouw account > Account MetriX > Credentials. Download daar de MT5-desktopinstaller. Installeer MT5, log in met het demo-accountnummer, master password en de exacte server uit Credentials. Deel het wachtwoord niet via GitHub of Railway.

Installeer Python 3.12 voor Windows, 64-bit, van https://www.python.org/downloads/windows/ . Selecteer bij installatie Python Launcher en Add python.exe to PATH.

In MT5: Market Watch > rechtsklik > Symbols. Zoek het S&P 500-contract van jouw server. Noteer de exacte naam, inclusief eventuele suffix. Neem US500.cash of US500 alleen over als dit echt de naam op jouw server is. Open daarvan een M5-chart, zet Tools > Options > Charts > Max bars in chart op minimaal 20000, laad historie door terug te scrollen en wacht tot die is gedownload. De bridge vraagt maximaal 12000 afgesloten M5-bars op. Hij gebruikt tick volume, dus de strategie kan andere signalen geven dan met SPY-aandelenvolume.

Voor DRY_RUN hoeft Algo Trading nog niet aan. Voor demo-orders later: Tools > Options > Expert Advisors, sta algoritmische handel toe en schakel Disable automated trading via external Python API UIT; zet vervolgens de Algo Trading-knop aan.

## 3. Bestanden lokaal plaatsen

Download het pakket op de VPS en pak het uit zodat deze bestanden bestaan:

```
C:\sp500\bot.py
C:\sp500\ftmo_guard.py
C:\sp500\requirements.txt
C:\sp500\mt5_bridge\worker.py
C:\sp500\mt5_bridge\server.py
```

Gebruik één VPS/worker per account. Het pakket bevat een snapshot van je huidige strategiecode; latere updates in GitHub worden niet automatisch naar de VPS gekopieerd.

Open PowerShell en voer uit:

```powershell
cd C:\sp500
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\mt5_bridge\requirements-windows.txt
Copy-Item .\mt5_bridge\.env.example .\mt5_bridge\.env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
notepad .\mt5_bridge\.env
```

Bewaar de gegenereerde token in .env en later in Railway. Vul in:

```
BRIDGE_URL=https://NOG_IN_TE_VULLEN.up.railway.app
BRIDGE_TOKEN=DE_GEZELF_GEGENEREERDE_TOKEN
BRIDGE_MODE=DRY_RUN
MT5_PATH=C:\Program Files\FTMO MetaTrader 5\terminal64.exe
MT5_LOGIN=JOUW_DEMO_ACCOUNTNUMMER
MT5_SERVER=EXACTE_SERVER_UIT_CREDENTIALS
MT5_PASSWORD=JOUW_MASTER_PASSWORD
MT5_SYMBOL=EXACTE_BROKER_SYMBOOLNAAM
```

Controleer MT5_PATH via de eigenschappen van de MT5-snelkoppeling. Is je wachtwoord voorzien van # of spaties, zet de volledige waarde in enkele aanhalingstekens voor python-dotenv. Controleer dat Notepad het bestand als .env opslaat, niet .env.txt. Houd deze map op de VPS privé.

## 4. Code naar GitHub uploaden

Open https://github.com/Rsch030/sp500 op de VPS. Maak via de branch-selector een branch mt5-bridge-demo vanaf main. Kies Add file > Upload files en upload de map mt5_bridge uit het pakket. Bewaar de mapstructuur: server.py moet op mt5_bridge/server.py staan. Commit naar mt5-bridge-demo.

Upload uitsluitend de distributiebestanden. Upload NOOIT .env, worker.log, worker.lock, journal.sqlite of je .venv. De distributie bevat een .gitignore in mt5_bridge; die helpt bij git-uploads, maar beschermt niet tegen handmatig uploaden via de website.

bot.py, ftmo_guard.py en requirements.txt staan al in je repository. Gebruik deze bestaande bestanden voor de Railway-build. De bridge is een nieuwe aparte service op de nieuwe branch.

## 5. Railway-service instellen

Open jouw bestaande project:
https://railway.com/project/cfe19bb2-a449-4363-b89f-abccc1d2c0b9

Klik New > GitHub Repo > Rsch030/sp500. Geef de NIEUWE service de naam mt5-bridge. Selecteer in Settings > Source branch mt5-bridge-demo. Laat Root Directory op / staan. Stel Railway Config File in op /mt5_bridge/railway.json. De eerste automatische deployment kan starten voordat je de configuratie hebt ingevuld; pas de instellingen toe en redeploy daarna.

Controleer:

| Instelling | Waarde |
|---|---|
| Builder | Dockerfile |
| Dockerfile path | mt5_bridge/Dockerfile |
| Start command | python -m mt5_bridge.server |
| Healthcheck | /health |
| Replicas | 1 |
| Serverless / sleep | uit |

Voeg onder Variables uitsluitend deze waarden toe:

```
BRIDGE_TOKEN=DEZELFDE_TOKEN_ALS_OP_DE_VPS
MT5_SYMBOL=DEZELFDE_EXACTE_SYMBOOLNAAM
BRIDGE_STRATEGY=TREND_PULLBACK
RUN_MODE=FTMO_PAPER
DATA_DIR=/tmp/bridge-import
```

Geen MT5-wachtwoord of login op Railway. RUN_MODE bepaalt hier de bestaande signaalfilters, niet accountcompliance of uitvoering. TREND_PULLBACK is één gekozen strategie; niet alle zes tegelijk. Je kunt later één andere sleutel uit bot.STRATEGIES kiezen. Deze strategie-instelling is geen bewijs van winstgevendheid.

Deploy en wacht op Success. Settings > Networking > Generate Domain. Kopieer de HTTPS-URL en zet die op de VPS in BRIDGE_URL. /health moet status ok tonen. Dat bewijst alleen dat de webservice draait. Deze aparte Railway-service verbruikt resources naast je bestaande paperbot; er is geen betaalde resource door dit pakket besteld.

## 6. Verbinding in DRY_RUN testen

Houd MT5 open. Start op de VPS:

```powershell
cd C:\sp500
.\.venv\Scripts\python.exe -m mt5_bridge.worker
```

Je ziet elke circa 30 seconden DRY_RUN en WAIT/WARMUP of een signaal. DRY_RUN leest echte brokerkoersen maar verstuurt geen orders. De worker accepteert alleen de exact geconfigureerde demo-accountidentiteit en USD-valuta. Als FTMO het account niet als demo aan MT5 rapporteert, blokkeert de worker.

Controleer in een tweede PowerShell-venster, zonder token te typen in de commandoregelgeschiedenis:

```powershell
cd C:\sp500
@'
from pathlib import Path
from dotenv import dotenv_values
import requests
e=dotenv_values(Path('mt5_bridge/.env'))
r=requests.get(e['BRIDGE_URL'].rstrip('/')+'/bridge/status',headers={'Authorization':'Bearer '+e['BRIDGE_TOKEN']},timeout=20)
r.raise_for_status()
print(r.json())
'@ | .\.venv\Scripts\python.exe -
```

connected=True met recente last_seen, jouw symbol, accountbalans en mode=DRY_RUN bewijst dat de bridge MT5-data ontvangt. Login/wachtwoord worden niet weergegeven. WARMUP betekent extra M5-historie laden. STALE_OR_FUTURE_CANDLE is normaal buiten handelstijden; tijdens de sessie controleer je MT5-verbinding en de Windows-klok. Een lege signaalrespons is geen verbindingsfout.

## 7. Demo-orders activeren

Stop de worker met Ctrl+C. Zet in .env BRIDGE_MODE=DEMO. Zet MT5 Algo Trading en externe Python-handel aan zoals hierboven. Start opnieuw. Deze versie blokkeert echte/funded accounts en maakt geen geforceerde testtrade.

Uitvoering: maximaal één positie of pending order over het HELE account. Stoprisico maximaal $100 / 0,1% van equity, laagste van beide, exclusief commissie/slippage. Lotgrootte wordt berekend met broker order_calc_profit en naar beneden afgerond. Minimale lotgrootte te groot? Dan wordt het signaal overgeslagen. SL en TP gaan mee in de brokerorder. Verouderde koersen, te grote spread, te grote afwijking van het signaal, onvoldoende margin, order_check-fouten en verkeerde accountidentiteit blokkeren de order.

De worker zet voor order_send een blijvende UNCERTAIN-record in journal.sqlite. Na een bevestigde volledige/gedeeltelijke uitvoering wordt die SENT. Bij timeout, crash of een niet-succesvolle retourcode wordt niets automatisch opnieuw geprobeerd en worden volgende orders geblokkeerd. Inspecteer dan de brokerhistorie en het journal voordat je dit handmatig herstelt; verwijder het journal niet om door te handelen. Verwijderen kan duplicaten veroorzaken. Een lokale bestandslock blokkeert twee workers in dezelfde map, niet op twee verschillende VPS'en.

Deze eerste versie gebruikt vaste SL/TP; het dynamisch sluiten, trailing en maximum-hours uit de paperbot worden niet gespiegeld. De VPS controleert equity alleen per pollingcyclus. De interne stop bij $1000 verlies vanaf de eerste observatie van de Prague-dag en een equityvloer van $95000 zijn conservatieve testinstellingen; dit is GEEN complete FTMO 1-Step-regelbewaking. De eerste observatie is geen gegarandeerde middernachtbalans. Geen funded account gebruiken met deze versie.

## 8. Automatisch starten zolang de Windows-sessie bestaat

Test eerst handmatig. Open Task Scheduler > Create Task:

- General: naam MT5 Bridge; dezelfde Windows-gebruiker als MT5; Run only when user is logged on.
- Triggers: At log on voor die gebruiker, 60 seconden vertraging.
- Actions: programma powershell.exe; argumenten -NoProfile -ExecutionPolicy Bypass -File C:\sp500\mt5_bridge\start.ps1 ; Start in C:\sp500.
- Conditions: haal onnodige idle-voorwaarden weg.
- Settings: Allow task to be run on demand; restart bij fout elke minuut; Do not start a new instance; zet Stop the task if it runs longer than UIT.

Zet tevens MT5 in Startup voor dezelfde gebruiker via Win+R > shell:startup en een MT5-snelkoppeling. De Python initialize-call kan MT5 ook starten; controleer na herstart toch de correcte terminal/accountverbinding.

Verbreek de RDP-verbinding als je klaar bent; kies niet Sign out/Afmelden. Deze configuratie vereist een ingelogde Windows-sessie. Na een VPS-reboot moet je opnieuw inloggen voordat deze login-trigger draait. Hij is dus niet autonoom na reboot; automatische login is niet door dit pakket ingesteld. Controleer /bridge/status na iedere reboot.

Logs: C:\sp500\mt5_bridge\worker.log. Schakel DEMO terug naar DRY_RUN en herstart de worker om nieuwe orders te stoppen. Bestaande posities behouden broker-SL/TP en worden hiermee niet gesloten.

## Bronnen en validatie

- https://ftmo.com/en/faq/how-do-i-log-in-to-mt5/
- https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5terminalinfo_py
- https://docs.railway.com/deployments/start-command
- https://learn.microsoft.com/en-us/windows-app/get-started-connect-devices-desktops-apps

Lokaal getest: authenticatie, verkeerde symbolen, verse/verouderde candledata, stabiele signaal-ID, lotafronding, ongeldige sizing en blokkeren van verkeerde/echte accounts. Zes unittest-tests geslaagd op Linux met gemockte signaalengine. MT5 order_check/order_send, Windows Taakplanner, de brokercontracten en VPS-netwerk zijn niet in een echte Windows-terminal getest. Controleer die in DRY_RUN en daarna op demo voordat je op uitvoering vertrouwt.
