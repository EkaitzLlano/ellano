import csv  # <-- 1. IMPORTACIÓN AÑADIDA (¡CRÍTICO!)
from ldap3 import Server, Connection, ALL, extend
import hashlib
import base64
import os
import sys

# =================================================================
#                 CONFIGURACIÓN DEL SERVIDOR Y CREDENCIALES
# -----------------------------------------------------------------
# ⚠️ CONFIGURACIÓN AJUSTADA A 192.168.1.20 y ellano.local ⚠️
# =================================================================
LDAP_SERVER = 'ldap://192.168.1.20:389'      # IP del Ubuntu Server
BIND_DN = 'cn=admin,dc=ellano,dc=ldap'        # DN de tu usuario administrador
BIND_PASSWORD = 'Qwerty123'               # Contraseña del administrador (¡MODIFICA ESTO!)
BASE_DN = 'dc=ellano,dc=ldap'                   # Nuevo DN base
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
    try:
        if conn.add(dn, object_classes, attributes):
            print(f"✅ Creado: {dn}")
            return True
        # Comprueba si el error es 'already exists'
        elif conn.result['description'] == 'entryAlreadyExists':
            print(f"➡️ Ya existe: {dn}")
            return True
        else:
            # Imprime el error específico si no es 'already exists'
            print(f"❌ Error al crear {dn}: {conn.result['description']} ({conn.result['message']})")
            return False
    except Exception as e:
        print(f"❌ Excepción grave al crear {dn}: {e}")
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
        # El 'import csv' ya está arriba del script
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Ignora líneas de comentario o vacías en el CSV
                if row and ('uid' in row) and (not row['uid'].startswith('#') and row['uid'].strip()):
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
    
    # --- 2. JERARQUÍA MODIFICADA ---
    
    # 1. Crear la UO raíz: CIP Tafalla
    cip_tafalla_dn = f'ou=CIP Tafalla,{BASE_DN}'
    create_entry(conn, cip_tafalla_dn, ['organizationalUnit', 'top'], {'ou': 'CIP Tafalla'})

    # 2. Crear la UO principal (Informatica) DENTRO de CIP Tafalla
    informatica_dn = f'ou=Informatica,{cip_tafalla_dn}'
    create_entry(conn, informatica_dn, ['organizationalUnit', 'top'], {'ou': 'Informatica'})

    # 3. Crear las UOs de las Mesas (MesaDelante, etc.) DENTRO de Informatica
    
    # --- 3. FILTRO AÑADIDO (Evita error de NoneType) ---
    valid_uos = [uo for uo in uos_a_crear if uo] # Filtra None o strings vacíos
    
    for uo_mesa in sorted(valid_uos):
        uo_dn = f'ou={uo_mesa},{informatica_dn}'
        create_entry(conn, uo_dn, ['organizationalUnit', 'top'], {'ou': uo_mesa})

    # =================================================================
    # --- BLOQUE 'PASO 2' CORREGIDO ---
    # =================================================================

    # Inicializamos contadores para los IDs
    next_uid_number = 10000
    next_gid_number = 10001
    default_user_gid = '10000' # Asumimos que 10000 es el GID de un grupo como "users"
    
    # 4. CREACIÓN DE USUARIOS
    print("\n--- PASO 2: CREANDO USUARIOS ---")
    
    for user in users_data:
        # DN del usuario: cn=NOMBRE,ou=MESA,ou=INFORMATICA,ou=CIP TAFALLA,dc=...
        user_dn = f"cn={user['cn']},ou={user['uo_mesa']},{informatica_dn}"
        
        attributes = {
            'cn': user['cn'],
            'sn': user['sn'],
            'givenName': user['givenName'],
            'uid': user['uid'],
            'userPassword': hash_password(TEMP_PASSWORD),
            
            # --- ✅ ATRIBUTOS POSIX GENERADOS ---
            'uidNumber': str(next_uid_number),
            'gidNumber': default_user_gid, # ID del grupo principal del usuario
            'homeDirectory': f"/home/{user['uid']}",
            'loginShell': '/bin/bash'
        }
        
        # --- ✅ CORREGIDO: 'posixGroup' -> 'posixAccount' ---
        object_classes = ['posixAccount', 'person', 'organizationalPerson', 'inetOrgPerson']
        
        if create_entry(conn, user_dn, object_classes, attributes):
            grupo_cn = user['grupo_cn']
            grupos_a_crear[grupo_cn]['members'].append(user_dn)
        
        next_uid_number += 1 # Incrementamos el ID para el siguiente usuario

    # =================================================================
    # --- BLOQUE 'PASO 3' CORREGIDO ---
    # =================================================================
    
    # 5. CREACIÓN DE GRUPOS Y ASIGNACIÓN DE MIEMBROS
    print("\n--- PASO 3: CREANDO GRUPOS Y ASIGNANDO MIEMBROS ---")
    
    for grupo_cn, data in grupos_a_crear.items():
        uo_mesa = data['uo_mesa']
        members = data['members']
        
        # DN del grupo: cn=GRUPO,ou=MESA,ou=INFORMATICA,ou=CIP TAFALLA,dc=...
        group_dn = f'cn={grupo_cn},ou={uo_mesa},{informatica_dn}'
        
        attributes = {
            'cn': grupo_cn,
            'objectClass': ['posixGroup', 'groupOfNames', 'top'],
            'member': members,
            # --- ✅ ATRIBUTO gidNumber AÑADIDO (¡CRÍTICO!) ---
            'gidNumber': str(next_gid_number) 
        }

        # Comprobamos que haya miembros antes de crear (LDAP a veces lo exige)
        if members:
            create_entry(conn, group_dn, attributes['objectClass'], attributes)
            next_gid_number += 1 # Incrementamos el ID para el siguiente grupo
        else:
            print(f"⚠️ Saltando grupo {grupo_cn} (sin miembros)")
            
    # 6. Cierre de la conexión
    conn.unbind()
    print("\n✨ Proceso de carga masiva finalizado. ✨")

if __name__ == '__main__':
    try:
        main()
    except NameError as e:
        print(f"Error: {e}")
        print("Asegúrate de haber importado 'csv' y tener 'ldap3' instalado (pip install ldap3)")
