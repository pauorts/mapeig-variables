# setup-and-run-batch.ps1

Write-Host "Preparando entorno para proceso batch..." -ForegroundColor Cyan
Write-Host ""

# Variables
$DB_USER = "user_tool"
$DB_NAME = "snomed_db"
$CONTAINER_NAME = "postgres-tool"
$SQL_FILE = "IRBD_Multibase_PostgreSQL_full/IRBD_Multibase_PostgreSQL_full_20251201.sql"

# Función para mostrar errores
function Exit-WithError {
    param([string]$Message)
    Write-Host "❌ ERROR: $Message" -ForegroundColor Red
    exit 1
}

# Validar que el contenedor está running
Write-Host "Verificando contenedor $CONTAINER_NAME..." -ForegroundColor Yellow
$containerExists = docker ps | Select-String $CONTAINER_NAME
if (-not $containerExists) {
    Exit-WithError "Contenedor $CONTAINER_NAME no está en ejecución. Ejecuta: docker-compose up -d"
}

# Validar que el archivo SQL existe
if (-not (Test-Path $SQL_FILE)) {
    Exit-WithError "Archivo $SQL_FILE no encontrado"
}

# ====== PASO 0: Limpiar BD existente si existe ======
Write-Host "Paso 0: Verificando si existe BD anterior..." -ForegroundColor Yellow
$dbExists = docker exec -i $CONTAINER_NAME psql -U $DB_USER -d postgres -lqt | Select-String $DB_NAME
if ($dbExists) {
    Write-Host "BD $DB_NAME ya existe. Eliminando..." -ForegroundColor Yellow
    docker exec -i $CONTAINER_NAME psql -U $DB_USER -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No se pudo eliminar BD anterior (continuando...)" -ForegroundColor Yellow
    } else {
        Write-Host "BD anterior eliminada" -ForegroundColor Green
    }
    Start-Sleep -Seconds 2
}

# ====== PASO 1: Crear BD ======
Write-Host "Paso 1: Creando base de datos $DB_NAME..." -ForegroundColor Cyan
docker exec -i $CONTAINER_NAME psql -U $DB_USER -d postgres -c "CREATE DATABASE $DB_NAME;" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "BD ya existe o error (continuando...)" -ForegroundColor Yellow
}

# ====== PASO 2: Copiar SQL ======
Write-Host "Paso 2: Copiando volcado SQL al contenedor..." -ForegroundColor Cyan
docker cp "$SQL_FILE" "$CONTAINER_NAME`:/tmp/volcado.sql"
if ($LASTEXITCODE -ne 0) {
    Exit-WithError "Error al copiar archivo SQL"
}

# ====== PASO 3: Restaurar datos ======
Write-Host "Paso 3: Restaurando datos (esto puede tardar 5-15 minutos)..." -ForegroundColor Cyan
$restoreStart = Get-Date
docker exec -i $CONTAINER_NAME pg_restore -U $DB_USER -d $DB_NAME -O /tmp/volcado.sql
if ($LASTEXITCODE -ne 0) {
    Exit-WithError "Error al restaurar la base de datos"
}
$restoreEnd = Get-Date
$restoreTime = ($restoreEnd - $restoreStart).TotalSeconds
Write-Host "Restauración completada en $([math]::Round($restoreTime, 2))s" -ForegroundColor Green

# Verificar que la BD tiene datos
Write-Host "Verificando que BD se restauró correctamente..." -ForegroundColor Yellow
$tableCount = docker exec -i $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema != 'pg_catalog' AND table_schema != 'information_schema';" 2>&1
Write-Host "Tablas encontradas: $tableCount" -ForegroundColor Green
 
# Verificar acceso a tabla específica
Write-Host "Verificando permisos en tabla snomedct_irbd_full.glsd_description..." -ForegroundColor Yellow
$testQuery = docker exec -i $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM snomedct_irbd_full.glsd_description LIMIT 1;" 2>&1
Write-Host "Acceso verificado" -ForegroundColor Green
 
# Esperar a que PostgreSQL termine procesos internos (VACUUM, etc.)
Write-Host "Esperando 30s a que PostgreSQL termine procesos internos..." -ForegroundColor Yellow
Start-Sleep -Seconds 30
Write-Host "Listo para ejecutar batch" -ForegroundColor Green
 
Write-Host ""

# ====== PASO 4: Ejecutar proceso batch ======
Write-Host "Paso 4: Ejecutando proceso batch..." -ForegroundColor Cyan
$batchStart = Get-Date
docker-compose --profile tools run --rm process-reference
if ($LASTEXITCODE -ne 0) {
    Exit-WithError "Error en proceso batch"
}
$batchEnd = Get-Date
$batchTime = ($batchEnd - $batchStart).TotalSeconds
Write-Host "Proceso batch completado en $([math]::Round($batchTime, 2))s" -ForegroundColor Green

Write-Host ""

Write-Host "Archivos de métricas generados en .\metrics_output\" -ForegroundColor Green
Get-ChildItem .\metrics_output\ -ErrorAction SilentlyContinue | Format-Table Name, Length, LastWriteTime

# ====== PASO 5: Limpieza ======
Write-Host "Paso 5: Iniciando limpieza..." -ForegroundColor Yellow

Write-Host "Eliminando base de datos $DB_NAME..." -ForegroundColor Cyan
docker exec -i $CONTAINER_NAME psql -U $DB_USER -d postgres -c "DROP DATABASE $DB_NAME;"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error al eliminar BD (continuando...)" -ForegroundColor Yellow
}

Write-Host "Eliminando imagen Docker..." -ForegroundColor Cyan
docker rmi eina-mapeig-process-reference 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Imagen eliminada" -ForegroundColor Green
} else {
    Write-Host "Imagen no encontrada (ignorando)" -ForegroundColor Yellow
}

# ====== RESUMEN ======
Write-Host ""
Write-Host "TODO COMPLETADO EXITOSAMENTE" -ForegroundColor Green
Write-Host "Tiempo restauración: $([math]::Round($restoreTime, 2))s" -ForegroundColor Green
Write-Host "Tiempo batch: $([math]::Round($batchTime, 2))s" -ForegroundColor Green
Write-Host "Espacio liberado: ~3.2 GB (imagen) + datos BD" -ForegroundColor Green