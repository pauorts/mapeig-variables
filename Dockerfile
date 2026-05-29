FROM python:3.11-slim-bullseye

# Instalem FreeTDS i controladors ODBC per poder conectar-nos a les sybase de ccc
USER root

ADD /drivers/oracle-instantclient19.5-basiclite-19.5.0.0.0-1.x86_64.rpm /tmp/oracle.rpm

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gettext \
        libgettextpo-dev \
        g++ \
        build-essential \
        libaio1 \
        libpq-dev \
        alien \
        libsasl2-dev \
        python3-dev \
        libldap2-dev \
        libssl-dev \
        openjdk-17-jdk \
        openjdk-17-jre \
        freetds-bin \
        freetds-dev \
        tdsodbc \
        unixodbc-dev \
        iputils-ping \
        dos2unix \
        curl \
        cron && \
    cd /tmp/ && \
    alien -d oracle.rpm && \
    dpkg -i oracle-instantclient19.5-basiclite_19.5.0.0.0-2_amd64.deb && \
    rm -rf oracle* && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# Configurar variables de entorno Java
ENV JAVA_HOME /usr/lib/jvm/java-17-openjdk-amd64/
ENV PATH="$JAVA_HOME/bin:$PATH"
RUN export JAVA_HOME

# Crear directorio para drivers JDBC
RUN mkdir -p /opt/jdbc

# Añadir drivers JDBC existentes
ADD /drivers/jtds-1.3.1.jar /usr/lib/jvm/java-17-openjdk-amd64/lib/jtds-1.3.1.jar
ADD /drivers/mssql-jdbc-12.8.0.jre11.jar /usr/lib/jvm/java-17-openjdk-amd64/lib/mssql-jdbc-12.8.0.jre11.jar

# Descargar driver JDBC oficial de Microsoft (compatible con Java 17)
RUN curl -L -o /opt/jdbc/mssql-jdbc.jar \
    https://github.com/microsoft/mssql-jdbc/releases/download/v12.6.1/mssql-jdbc-12.6.1.jre11.jar

# Configurar FreeTDS
RUN printf '[FreeTDS]\nDescription=FreeTDS ODBC driver for Sybase and SQL Server\nDriver=/usr/lib/x86_64-linux-gnu/odbc/libtdsodbc.so\nUsageCount=1\n' > /etc/odbcinst.ini

# Instalar dependencias de Python
COPY ./requirements.txt /requirements.txt
 
RUN pip install --upgrade "pip>=23.2" && \
    pip install --no-cache-dir -r /requirements.txt
 
# Instalar dependencias adicionales
RUN pip install --no-cache-dir fastapi uvicorn jaydebeapi

# Estructura de la aplicación (alineado con Dockerfile.batch)
RUN mkdir -p /app
WORKDIR /app
COPY . /app
ENV PYTHONPATH=/app

COPY app/cron/crontab /etc/cron.d/mi-cron-app
RUN dos2unix /etc/cron.d/mi-cron-app && \
    chmod 0644 /etc/cron.d/mi-cron-app && \
    chmod +x /app/app/cron/*.py

EXPOSE 8000

# alembic aplica migraciones pendientes; init_db hace el seed; luego arranca uvicorn
CMD ["sh", "-c", "printenv > /etc/environment && cron && alembic upgrade head && python -m app.db.init_db && uvicorn app.main:app --host 0.0.0.0 --port 8000"]



