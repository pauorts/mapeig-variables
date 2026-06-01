# Eina de Mapeig — Guia de Desplegament

Aplicació FastAPI + PostgreSQL + Nginx desplegada amb Docker Compose. Inclou un procés batch pesat (`process-reference`) que s'executa sota demanda i es destrueix automàticament en finalitzar.

---

## Prerequisits

- Docker Desktop en execució
- Fitxer `.env` configurat a l'arrel del projecte
- PowerShell 5.1+ (Windows) per al script batch .ps1 // linux per script .sh

---

## 1. Aixecar l'aplicació

```powershell
docker-compose up -d --build
```

Aixeca tres serveis:

| Contenidor | Rol |
|---|---|
| `postgres-tool` | Base de dades PostgreSQL 16 (port `5454`) |
| `fastapi-tool` | Backend FastAPI + cron intern |
| `nginx-tool` | Proxy invers + servei d'estàtics (port `1077`) |

En arrencar, el backend executa automàticament:
1. `cron` — inicia el dimoni cron intern del contenidor
2. `alembic upgrade head` — aplica les migracions pendents
3. `python -m app.db.init_db` — seed inicial de la base de dades
4. `uvicorn` — arrenca el servidor API

---

## 2. Gestió d'usuaris

Els usuaris es creen i gestionen directament des del contenidor del backend.

**Crear un usuari nou:**
```powershell
docker exec -it fastapi-tool python -m app.db.init_db
```

> El mòdul `init_db` accepta arguments per crear usuaris addicionals. Consultar la implementació per als paràmetres exactes.

---

## 3. Estàtics

Els fitxers estàtics (`app/static/`) es munten directament a Nginx en mode lectura i es serveixen sense passar pel backend. No cal cap pas addicional: qualsevol canvi a la carpeta `app/static/` és visible immediatament sense reiniciar cap contenidor.

```
./app/static  →  nginx:/usr/share/nginx/html/static  (ro)
```

---

## 4. Procés batch — Càrrega de referència SNOMED

El servei `process-reference` és un contenidor pesat (models LLM + dades SNOMED) que s'executa **sota demanda** i s'elimina en finalitzar. Està exclòs del `docker-compose up` normal mitjançant el perfil `tools`.

### Prerequisits del batch

- Arxiu SQL de SNOMED: `IRBD_Multibase_PostgreSQL_full/IRBD_Multibase_PostgreSQL_full_20251201.sql`
- Arxiu d'arquetips openEHR: `archetypes_2026_01_29-15_34_10.zip`
- Contenidors de l'aplicació en execució (`docker-compose up -d`)

### Execució automàtica (recomanada)

**Windows (PowerShell):**
```powershell
.\setup-and-run-batch.ps1
```

**Linux:**
```bash
chmod +x setup-and-run-batch.sh
./setup-and-run-batch.sh
```

El script realitza els passos següents de forma seqüencial i amb validació en cada punt:

| Pas | Acció |
|---|---|
| 0 | Elimina la base de dades `snomed_db` si ja existia |
| 1 | Crea la base de dades `snomed_db` |
| 2 | Copia el volcament SQL al contenidor PostgreSQL |
| 3 | Restaura les dades (5–15 min) i verifica l'accés |
| 4 | Executa el procés batch (`app.cron.build_reference`) |
| 5 | Elimina la BD `snomed_db` i la imatge Docker del batch |

En finalitzar, els fitxers de mètriques queden a `.\metrics_output\`.

### Execució manual (pas a pas)

```powershell
# 1. Crear la BD SNOMED
docker exec -it postgres-tool psql -U user_tool -d postgres -c "CREATE DATABASE snomed_db;"

# 2. Copiar el volcament SQL
docker cp IRBD_Multibase_PostgreSQL_full/IRBD_Multibase_PostgreSQL_full_20251201.sql postgres-tool:/tmp/volcado.sql

# 3. Restaurar les dades
docker exec -it postgres-tool pg_restore -U user_tool -d snomed_db -O /tmp/volcado.sql

# 4. Executar el batch
docker-compose --profile tools run --rm process-reference

# 5. Netejar (opcional)
docker exec -it postgres-tool psql -U user_tool -d postgres -c "DROP DATABASE snomed_db;"
docker rmi eina-mapeig-process-reference
```

---

## 5. Cron intern

El dimoni cron s'inicia automàticament dins del contenidor `fastapi-tool` i no requereix cap acció manual. Els treballs configurats a `app/cron/crontab` són:

| Programa | Mòdul | Descripció |
|---|---|---|
| Diumenges 03:00 | `app.cron.update_metrics` | Actualització setmanal de mètriques |

Per consultar el log del cron en temps real:
```bash
docker exec -it fastapi-tool tail -f /var/log/cron.log
```

---

## 6. Execució de comandes aïllades (sense cron)

Per executar qualsevol mòdul Python de forma puntual dins del contenidor del backend, sense modificar el cron ni reiniciar serveis:

```powershell
docker exec -it fastapi-tool python -m <modul>
```

Exemples habituals:

```powershell
# Actualitzar mètriques manualment
docker exec -it fastapi-tool python -m app.cron.update_metrics

# Construir referència de forma aïllada (requereix snomed_db activa)
docker exec -it fastapi-tool python -m app.cron.build_reference
```

> Aquests comandos s'executen en primer pla i mostren la sortida directament al terminal. No afecten el cron intern ni cap altre procés en execució.

---

## 7. Aturar i netejar

```powershell
# Aturar serveis (conserva les dades)
docker-compose down

# Aturar i eliminar volums (destrueix la BD)
docker-compose down -v
```

---

## Estructura de serveis

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│  nginx-tool │────▶│ fastapi-tool │────▶│ postgres-tool │
│  :1077      │     │  :8000       │     │  :5454        │
└─────────────┘     └──────────────┘     └───────────────┘
                           │
                    (sota demanda)
                    ┌──────────────────┐
                    │ process-reference│
                    │  perfil: tools   │
                    └──────────────────┘
```

##### REPO GITHUB #######
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/pauorts/mapeig-variables.git
git branch -M main
git push -u origin main

##### DESPLEGAMENT AL SERVER ######
mkdir eina-mapeig
git clone https://github.com/pauorts/mapeig-variables.git ///// git pull origin
scp -r IRBD_Multibase_PostgreSQL_full usuario@ip-servidor::eina-mapeig/mapeig-variables
scp -r app/embedding_cache usuario@ip-servidor::eina-mapeig/mapeig-variables/app
scp .env usuario@ip-servidor::eina-mapeig/mapeig-variables
scp -r SOCMIC_FOLDER usuario@ip-servidor::eina-mapeig/mapeig-variables

--> mateixos pasos per desplegar docker + executar comandes
