#!/bin/bash
set -euo pipefail

echo -e "\e[36mPreparant entorn per al procés batch...\e[0m"
echo ""

# Variables
DB_USER="user_tool"
DB_NAME="snomed_db"
CONTAINER_NAME="postgres-tool"
SQL_FILE="IRBD_Multibase_PostgreSQL_full/IRBD_Multibase_PostgreSQL_full_20251201.sql"

exit_with_error() {
    echo -e "\e[31m❌ ERROR: $1\e[0m" >&2
    exit 1
}

# Validar que el contenidor està en execució
echo -e "\e[33mVerificant contenidor $CONTAINER_NAME...\e[0m"
if ! sudo docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    exit_with_error "Contenidor $CONTAINER_NAME no està en execució. Executa: docker-compose up -d"
fi

# Validar que el fitxer SQL existeix
[ -f "$SQL_FILE" ] || exit_with_error "Fitxer $SQL_FILE no trobat"

# ====== PAS 0: Netejar BD existent si existeix ======
DB_EXISTS=$(sudo docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")
if [ "$DB_EXISTS" = "1" ]; then
    echo -e "\e[33mBD $DB_NAME ja existeix. Eliminant...\e[0m"
    if sudo docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null; then
        echo -e "\e[32mBD anterior eliminada\e[0m"
    else
        echo -e "\e[33mNo s'ha pogut eliminar la BD anterior (continuant...)\e[0m"
    fi
    sleep 2
fi

# ====== PAS 1: Crear BD ======
echo -e "\e[36mPas 1: Creant base de dades $DB_NAME...\e[0m"
sudo docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME;" 2>/dev/null \
    || echo -e "\e[33mBD ja existeix o error (continuant...)\e[0m"

# ====== PAS 2: Copiar SQL ======
echo -e "\e[36mPas 2: Copiant volcament SQL al contenidor...\e[0m"
sudo docker cp "$SQL_FILE" "$CONTAINER_NAME:/tmp/volcado.sql" \
    || exit_with_error "Error en copiar el fitxer SQL"

# ====== PAS 3: Restaurar dades ======
echo -e "\e[36mPas 3: Restaurant dades (això pot trigar 5-15 minuts)...\e[0m"
restore_start=$(date +%s)
sudo docker exec -i "$CONTAINER_NAME" pg_restore -U "$DB_USER" -d "$DB_NAME" -O /tmp/volcado.sql \
    || exit_with_error "Error en restaurar la base de dades"
restore_end=$(date +%s)
restore_time=$((restore_end - restore_start))
echo -e "\e[32mRestauració completada en ${restore_time}s\e[0m"

# Verificar que la BD té dades
echo -e "\e[33mVerificant que la BD s'ha restaurat correctament...\e[0m"
table_count=$(sudo docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema');" 2>&1)
echo -e "\e[32mTaules trobades: $table_count\e[0m"

# Verificar accés a taula específica
echo -e "\e[33mVerificant permisos a la taula snomedct_irbd_full.glsd_description...\e[0m"
sudo docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" \
    -c "SELECT COUNT(*) FROM snomedct_irbd_full.glsd_description LIMIT 1;" 2>&1
echo -e "\e[32mAccés verificat\e[0m"

# Esperar que PostgreSQL acabi processos interns (VACUUM, etc.)
echo -e "\e[33mEsperant 30s que PostgreSQL acabi processos interns...\e[0m"
sleep 30
echo -e "\e[32mLlest per executar batch\e[0m"

echo ""

# ====== PAS 4: Executar procés batch ======
echo -e "\e[36mPas 4: Executant procés batch...\e[0m"
batch_start=$(date +%s)
if docker compose version >/dev/null 2>&1; then
    sudo docker compose --profile tools run --rm process-reference \
        || exit_with_error "Error en el procés batch"
else
    sudo docker-compose --profile tools run --rm process-reference \
        || exit_with_error "Error en el procés batch"
fi
batch_end=$(date +%s)
batch_time=$((batch_end - batch_start))
echo -e "\e[32mProcés batch completat en ${batch_time}s\e[0m"

echo ""

echo -e "\e[32mFitxers de mètriques generats a ./metrics_output/\e[0m"
ls -lh ./metrics_output/ 2>/dev/null || true

# ====== PAS 5: Neteja ======
echo -e "\e[33mPas 5: Iniciant neteja...\e[0m"

echo -e "\e[36mEliminant base de dades $DB_NAME...\e[0m"
sudo docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "DROP DATABASE $DB_NAME;" \
    || echo -e "\e[33mError en eliminar la BD (continuant...)\e[0m"

echo -e "\e[36mEliminant imatge Docker...\e[0m"
if sudo docker rmi eina-mapeig-process-reference 2>/dev/null; then
    echo -e "\e[32mImatge eliminada\e[0m"
else
    echo -e "\e[33mImatge no trobada (ignorant)\e[0m"
fi

# ====== RESUM ======
echo ""
echo -e "\e[32mTOT COMPLETAT EXITOSAMENT\e[0m"
echo -e "\e[32mTemps restauració: ${restore_time}s\e[0m"
echo -e "\e[32mTemps batch: ${batch_time}s\e[0m"
echo -e "\e[32mEspai alliberat: ~3.2 GB (imatge) + dades BD\e[0m"
