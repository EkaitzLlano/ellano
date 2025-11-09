import csv
from ldap3 import Server, Connection, ALL, extend
import hashlib
import base64
import os
import sys

# =================================================================
#               CONFIGURACIÓN DEL SERVIDOR Y CREDENCIALES
# -----------------------------------------------------------------
# ⚠️ CONFIGURACIÓN AJUSTADA A 192.168.1.20 y ellano.local ⚠️
# =================================================================
LDAP_SERVER = 'ldap://192.168.1.20:389'           # IP del Ubuntu Server
BIND_DN = 'cn=admin,dc=ellano,dc=ldap'           # DN de tu usuario administrador
BIND_PASSWORD = 'Qwerty123'                 # Contraseña del administrador (¡MODIFICA ESTO!)
BASE_DN = 'dc=ellano,dc=ldap'                      # Nuevo DN base
# =================================================================
CSV_FILE = 'ldap.csv'
TEMP_PASSWORD = 'Qwerty123' # Contraseña temporal hasheada para todos los usuarios

def hash_password(password):
    """Hashea una contraseña para el atributo userPassword (SSHA)"""
    salt = os.urandom(4)
    hashed = hashlib.sha1(password.encode('utf8') + salt).digest()
    return '{SSHA}' + base64.b64encode(hashed + salt).decode('utf8')

def create_entry(conn, dn, object_classes, attributes):
    """Intenta crear una entrada en LDAP y maneja errores si ya existe."""
    if conn.add(dn, object_classes, attributes):
        print(f"✅ Creado: {dn}")
        return True
    elif 'already exists' in conn.result['description']:
        print(f"➡️ Ya existe: {dn}")
        return True
    else:
        print(f"❌ Error al crear {dn}: {conn.result['description']}")
        return False

def main():
    
    if not os.path.exists(CSV_FILE):
        print(f"FATAL: Archivo de datos '{CSV_FILE}' no encontrado en el directorio actual.")
        sys.exit(1)
        
    uos_a_crear = set()
    grupos_a_crear = {} 
    
    # 1. Conexión al servidor LDAP
    try:
        server = Server(LDAP_SERVER, get_info=ALL)
        conn = Connection(server, BIND_DN, BIND_PASSWORD, auto_bind=True)
        print(f"Conexión exitosa a {LDAP_SERVER}")
    except Exception as e:
        print(f"FATAL: No se pudo conectar al servidor LDAP. Error: {e}")
        sys.exit(1)

    # 2. Leer datos del CSV y recolectar la estructura
    users_data = []
    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                users_data.append(row)
                uos_a_crear.add(row['uo_mesa'])
                if row['grupo_cn'] not in grupos_a_crear:
                    grupos_a_crear[row['grupo_cn']] = {'uo_mesa': row['uo_mesa'], 'members': []}

    except Exception as e:
        print(f"Error al leer o procesar el archivo CSV: {e}")
        conn.unbind()
        sys.exit(1)


    # 3. CREACIÓN DE UNIDADES ORGANIZATIVAS (OU)
    print("\n--- PASO 1: CREANDO UNIDADES ORGANIZATIVAS (OU) ---")
    
    # Crear la UO principal (Informatica)
    informatica_dn = f'ou=Informatica,{BASE_DN}'
    create_entry(conn, informatica_dn, ['organizationalUnit', 'top'], {'ou': 'Informatica'})

    # Crear las UOs de las Mesas (MesaDelante, MesaProfesor, etc.)
    for uo_mesa in sorted(uos_a_crear):
        uo_dn = f'ou={uo_mesa},{informatica_dn}'
        create_entry(conn, uo_dn, ['organizationalUnit', 'top'], {'ou': uo_mesa})

    # 4. CREACIÓN DE USUARIOS
    print("\n--- PASO 2: CREANDO USUARIOS ---")
    
    for user in users_data:
        # DN del usuario: cn=NOMBRE,ou=MESA,ou=INFORMATICA,dc=ELLANO,dc=LOCAL
        user_dn = f"cn={user['cn']},ou={user['uo_mesa']},{informatica_dn}"
        
        attributes = {
            'cn': user['cn'],
            'sn': user['sn'],
            'givenName': user['givenName'],
            'uid': user['uid'],
            'userPassword': hash_password(TEMP_PASSWORD),
        }
        
        if create_entry(conn, user_dn, ['person', 'organizationalPerson', 'inetOrgPerson'], attributes):
            grupo_cn = user['grupo_cn']
            grupos_a_crear[grupo_cn]['members'].append(user_dn)

    # 5. CREACIÓN DE GRUPOS Y ASIGNACIÓN DE MIEMBROS
    print("\n--- PASO 3: CREANDO GRUPOS Y ASIGNANDO MIEMBROS ---")
    
    for grupo_cn, data in grupos_a_crear.items():
        uo_mesa = data['uo_mesa']
        members = data['members']
        
        # DN del grupo: cn=GRUPO,ou=MESA,ou=INFORMATICA,dc=ELLANO,dc=LOCAL
        group_dn = f'cn={grupo_cn},ou={uo_mesa},{informatica_dn}'
        
        attributes = {
            'cn': grupo_cn,
            'objectClass': ['groupOfNames', 'top'],
            'member': members 
        }

        create_entry(conn, group_dn, attributes['objectClass'], attributes)
        
    # 6. Cierre de la conexión
    conn.unbind()
    print("\n✨ Proceso de carga masiva finalizado. ✨")

if __name__ == '__main__':
    try:
        main()
    except NameError:
        print("Error: Asegúrate de haber instalado todas las librerías con 'pip install ldap3'")