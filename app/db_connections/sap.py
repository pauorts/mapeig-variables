import os
import requests
from xml.etree import ElementTree as ET

def connect2sap():
  sap_url: str = os.environ.get('SAP_URL')
  sap_usr: str = os.environ.get('SAP_USERNAME')
  sap_pwd: str = os.environ.get('SAP_PASSWORD')

  ## Inici login BO
  logonstring: str = '''<attrs xmlns="http://www.sap.com/rws/bip">
    <attr name="password" type="string">{password}</attr>
    <attr name="clientType" type="string"/>
    <attr name="auth" type="string" possibilities="secEnterprise,secLDAP,secWinAD,secSAPR3">secEnterprise</attr>
    <attr name="userName" type="string">{username}</attr>
  </attrs>'''

  sap_logon = (
    ET
      .tostring(element = ET.fromstring(logonstring), encoding = 'utf-8', method = 'xml')
      .decode()
      .format(username=sap_usr, password=sap_pwd)
  )

  ## Crear una sessió
  session = requests.Session()

  ## Obtenir el token d'accés de BO.
  response = session.post(
    sap_url + '/logon/long', 
    data = sap_logon, 
    headers = {'Content-Type': 'application/xml', 'Accept': 'application/xml'},
    verify=False)

  ## Afegir el token al header de les requests
  if response.status_code == 200:
    session.headers.update({'X-SAP-LogonToken': response.headers.get('X-SAP-LogonToken')})

  return(session)