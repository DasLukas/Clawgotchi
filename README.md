# Clawgotchi

Clawgotchi ist ein erweiterbares Raspberry-Pi-Projekt mit FastAPI-Weboberflaeche, REST-API, Theme-/Plugin-System und SQLite-Persistenz.

## Features

- Schichtenarchitektur: `domain`, `application`, `infrastructure`, `presentation`
- FastAPI REST API + Jinja2 Web-UI
- Setup-Wizard, Dashboard, Themes und Plugins
- SQLite-Statuspersistenz mit Snapshots
- Hintergrund-Worker fuer Tick-Loop und Command-Queue
- Dummy-Hardwaretreiber (Display/Input)

## Voraussetzungen

- Raspberry Pi OS Lite/Minimal (Debian-basiert)
- Internetzugang fuer `apt` und `pip`
- Git-Repository via SSH (`git@...`)
- Root-Rechte (z. B. `sudo`)

## Installation

### A) Automatische Installation (empfohlen)

Einzeiler:

```bash
curl -fsSL https://<YOUR_DOMAIN_OR_RAW_GIT_URL>/install.sh | sudo bash
```

Nicht-interaktiv (keine Rueckfragen, alle Pflichtwerte gesetzt):

```bash
curl -fsSL https://<YOUR_DOMAIN_OR_RAW_GIT_URL>/install.sh | sudo env \
  CLWG_USER=clawgotchi \
  CLWG_GIT_SSH_URL=git@github.com:ORG/REPO.git \
  CLWG_GIT_HOST=github.com \
  CLWG_UPDATE_TIME=03:30 \
  bash
```

Dry-Run (zeigt nur Aktionen, fuehrt nichts aus):

```bash
curl -fsSL https://<YOUR_DOMAIN_OR_RAW_GIT_URL>/install.sh | sudo env \
  CLWG_USER=clawgotchi \
  CLWG_GIT_SSH_URL=git@github.com:ORG/REPO.git \
  CLWG_GIT_HOST=github.com \
  CLWG_UPDATE_TIME=03:30 \
  CLWG_DRYRUN=1 \
  bash
```

Was der Installer macht:

- Legt Benutzer an (falls nicht vorhanden) oder verwendet bestehenden Benutzer.
- Installiert Systempakete, Python-Umgebung und `pip install -e .` in `/opt/clawgotchi/.venv`.
- Aktiviert SPI (non-interaktiv, falls moeglich) und setzt `dtparam=spi=on`.
- Konfiguriert `unattended-upgrades`.
- Erstellt `clawgotchi.service`.
- Erstellt naechtlichen Update-Job (`clawgotchi-update.service` + `clawgotchi-update.timer`) fuer `main`.
- Fuehrt Git-Operationen fuer Updates explizit als Zielbenutzer aus (nicht als root).

### B) Manuelle Installation

1. Systempakete installieren:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates curl git openssh-client \
  python3 python3-pip python3-venv \
  unattended-upgrades apt-listchanges
```

2. Benutzer anlegen (nur falls nicht vorhanden):

```bash
id -u clawgotchi >/dev/null 2>&1 || sudo useradd --create-home --shell /bin/bash clawgotchi
```

3. SPI aktivieren:

```bash
sudo raspi-config nonint do_spi 0
```

Zusatzlich sicherstellen, dass in `/boot/config.txt` (oder je nach System `/boot/firmware/config.txt`) Folgendes vorhanden ist:

```bash
dtparam=spi=on
```

4. SSH-Hinweis (optional, nicht automatisch aktivieren):

```bash
sudo systemctl enable --now ssh
```

5. Deploy-Key fuer Git-SSH vorbereiten (als Zielbenutzer):

```bash
sudo -u clawgotchi mkdir -p /home/clawgotchi/.ssh
sudo -u clawgotchi chmod 700 /home/clawgotchi/.ssh
sudo -u clawgotchi test -f /home/clawgotchi/.ssh/id_ed25519 || \
  sudo -u clawgotchi ssh-keygen -t ed25519 -N "" -f /home/clawgotchi/.ssh/id_ed25519 -C "clawgotchi-deploy@$(hostname -s)"
sudo -u clawgotchi cat /home/clawgotchi/.ssh/id_ed25519.pub
```

Public Key als Deploy Key (read-only empfohlen) im Git-Host hinterlegen. Danach Host-Key hinterlegen und Test:

```bash
sudo -u clawgotchi touch /home/clawgotchi/.ssh/known_hosts
sudo -u clawgotchi chmod 600 /home/clawgotchi/.ssh/known_hosts
sudo ssh-keyscan -H github.com | sudo tee -a /home/clawgotchi/.ssh/known_hosts >/dev/null
sudo chown clawgotchi:clawgotchi /home/clawgotchi/.ssh/known_hosts
sudo -u clawgotchi ssh -T git@github.com
```

6. Projekt nach `/opt/clawgotchi` klonen:

```bash
sudo mkdir -p /opt/clawgotchi
sudo chown -R clawgotchi:clawgotchi /opt/clawgotchi
sudo -u clawgotchi git clone git@github.com:ORG/REPO.git /opt/clawgotchi
sudo -u clawgotchi bash -lc "cd /opt/clawgotchi && git checkout main"
```

Falls bereits vorhanden:

```bash
sudo -u clawgotchi bash -lc "cd /opt/clawgotchi && git fetch origin && git checkout main && git pull --ff-only origin main"
```

7. Virtual Environment und Python-Abhaengigkeiten installieren:

```bash
sudo -u clawgotchi python3 -m venv /opt/clawgotchi/.venv
sudo -u clawgotchi /opt/clawgotchi/.venv/bin/pip install --upgrade pip setuptools wheel
sudo -u clawgotchi bash -lc "cd /opt/clawgotchi && /opt/clawgotchi/.venv/bin/pip install -e ."
```

8. `clawgotchi.service` erstellen:

```bash
sudo tee /etc/systemd/system/clawgotchi.service >/dev/null <<'EOF'
[Unit]
Description=Clawgotchi Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=clawgotchi
Group=clawgotchi
WorkingDirectory=/opt/clawgotchi
ExecStart=/opt/clawgotchi/.venv/bin/python /opt/clawgotchi/main.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
```

9. Unattended Upgrades aktivieren:

```bash
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
sudo systemctl enable --now unattended-upgrades
```

10. Update-Skript erstellen (`/usr/local/bin/clawgotchi-update.sh`):

```bash
sudo tee /usr/local/bin/clawgotchi-update.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

APP_USER="clawgotchi"
PROJECT_ROOT="/opt/clawgotchi"
VENV_PIP="/opt/clawgotchi/.venv/bin/pip"
GIT_URL="git@github.com:ORG/REPO.git"

su - "${APP_USER}" -c "cd '${PROJECT_ROOT}' && git remote set-url origin '${GIT_URL}' && git fetch origin && git checkout main && git pull --ff-only origin main"
su - "${APP_USER}" -c "cd '${PROJECT_ROOT}' && '${VENV_PIP}' install -e ."
systemctl restart clawgotchi.service
EOF
sudo chmod 755 /usr/local/bin/clawgotchi-update.sh
sudo chown root:root /usr/local/bin/clawgotchi-update.sh
```

11. Update-Service + Timer erstellen:

```bash
sudo tee /etc/systemd/system/clawgotchi-update.service >/dev/null <<'EOF'
[Unit]
Description=Clawgotchi Update Service
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/clawgotchi-update.sh
EOF
```

```bash
sudo tee /etc/systemd/system/clawgotchi-update.timer >/dev/null <<'EOF'
[Unit]
Description=Clawgotchi Nightly Update Timer

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
Timezone=Europe/Berlin
Unit=clawgotchi-update.service

[Install]
WantedBy=timers.target
EOF
```

12. Dienste aktivieren und pruefen:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clawgotchi.service
sudo systemctl enable --now clawgotchi-update.timer
sudo systemctl status clawgotchi.service
sudo systemctl status clawgotchi-update.timer
```

## Updating

Automatisches Update:

- Der Timer `clawgotchi-update.timer` startet taeglich um `03:30` (Zeitzone `Europe/Berlin`) den Update-Service.
- Update-Ablauf: `git fetch` -> `git checkout main` -> `git pull --ff-only` -> `pip install -e .` -> `systemctl restart clawgotchi.service`.

Manuelles Update aus dem Projektverzeichnis:

```bash
./update.sh
```

Hinweis:

- Das Skript bricht bei lokalen Git-Aenderungen bewusst ab (kein automatisches Merge).
- Wenn `update.sh` ohne root ausgefuehrt wird, wird der Service nicht neu gestartet.
- Git/SSH-Schritte laufen mit dem App-User `clawgotchi` (override via `CLWG_USER=<user>`).
- Fuer Update inklusive Service-Neustart:

```bash
sudo ./update.sh
```

Manuell sofort ausfuehren:

```bash
sudo systemctl start clawgotchi-update.service
```

Update ueber Webinterface:

- Unter `Settings` kann ein Update direkt gestartet werden.
- Die Seite zeigt den Rueckgabestatus sowie `stdout`/`stderr` des Skripts an.

## Configuration

### Installer-Variablen (`install.sh`)

- `CLWG_USER`: Linux-Benutzer fuer Betrieb und Git-Updates.
- `CLWG_GIT_SSH_URL`: SSH-Repository-URL (Pflichtwert).
- `CLWG_GIT_HOST`: Git-Host fuer `ssh-keyscan` und SSH-Test (optional, wird wenn moeglich aus URL abgeleitet).
- `CLWG_UPDATE_TIME`: Uhrzeit fuer den Timer im Format `HH:MM` (Default `03:30`).
- `CLWG_DRYRUN=1`: Nur anzeigen, nichts ausfuehren.
- `CLWG_SKIP_SSH_TEST=1`: SSH-Test nach Deploy-Key-Einrichtung ueberspringen (nur wenn bewusst gewuenscht).

### Laufzeit-Konfiguration der App

- `.env` mit Prefix `CLAW_` (siehe `.env.example`)
- `config/defaults.toml` als Standardkonfiguration
- Typische Werte: `CLAW_HOST`, `CLAW_PORT`, `CLAW_DATABASE_URL`, `CLAW_PLUGIN_DIRECTORY`, `CLAW_THEME_DIRECTORY`

## Betrieb und Verifikation

Service- und Timer-Status:

```bash
sudo systemctl status clawgotchi.service
sudo systemctl status clawgotchi-update.timer
```

Logs:

```bash
journalctl -u clawgotchi -f
journalctl -u clawgotchi-update.service -n 50
```

REST-Weboberflaeche:

- `http://<RASPBERRY_PI_IP>:8000/`
- API-Dokumentation: `http://<RASPBERRY_PI_IP>:8000/docs`

## Troubleshooting

### `Permission denied (publickey)`

- Deploy Key ist nicht im Repository hinterlegt oder falsches Repository.
- Pruefen, ob der richtige Public Key in den Deploy Keys liegt (read-only reicht).
- SSH-Test:

```bash
sudo -u clawgotchi ssh -T git@github.com
```

### `Host key verification failed`

- Host-Key fehlt oder ist veraltet.
- Erneut per `ssh-keyscan` eintragen:

```bash
sudo ssh-keyscan -H github.com | sudo tee -a /home/clawgotchi/.ssh/known_hosts >/dev/null
sudo chown clawgotchi:clawgotchi /home/clawgotchi/.ssh/known_hosts
sudo chmod 600 /home/clawgotchi/.ssh/known_hosts
```

### Service startet nicht

- Letzte Fehlerdetails lesen:

```bash
journalctl -u clawgotchi -n 100 --no-pager
sudo systemctl status clawgotchi.service
```

- Hauefige Ursachen: fehlgeschlagenes `pip install -e .`, falsche Dateirechte unter `/opt/clawgotchi`, Python-Umgebung beschaedigt.
