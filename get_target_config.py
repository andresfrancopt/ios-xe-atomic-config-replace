#! /usr/bin/env python
#
# get_target_config.py
#
# Connects to a Cisco IOS-XE device via NETCONF and retrieves the running
# configuration as YANG-modelled CLI text, then saves it as a ready-to-use
# candidate_target_config.xml for the ACR script (atomic_replace_config_v1.3.py).
#
# Device credentials are loaded from a .env file. Copy .env.sample to .env
# and fill in your device details before running.
#

from ncclient import manager
import lxml.etree as et
import xmltodict
import time
import os
from dotenv import load_dotenv

load_dotenv()

HOST     = os.getenv('DEVICE_HOST')
USERNAME = os.getenv('DEVICE_USERNAME')
PASSWORD = os.getenv('DEVICE_PASSWORD')
OUTPUT   = 'candidate_target_config.xml'

if not all([HOST, USERNAME, PASSWORD]):
    raise RuntimeError(
        "Missing device credentials. Copy .env.sample to .env and set "
        "DEVICE_HOST, DEVICE_USERNAME, and DEVICE_PASSWORD."
    )

get_modelled_config_running = '''<get-modelled-config-clis xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-cli-rpc">
                            <datastore>running</datastore>
                         </get-modelled-config-clis>'''


def netconf_connect(host, username, password, retries=5, retry_delay=30):
    for attempt in range(1, retries + 1):
        try:
            print(f"NETCONF connect attempt {attempt}/{retries}...")
            time.sleep(5)
            session = manager.connect(
                host=host,
                port=830,
                username=username,
                password=password,
                hostkey_verify=False,
                device_params={'name': 'iosxe'},
                manager_params={'timeout': 3600}
            )
            print("NETCONF session established.")
            return session
        except Exception as e:
            print(f"netconf: {e}")
            if attempt < retries:
                print(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                raise


def get_running_as_target_xml(session, output_file):
    print("Retrieving running config as YANG-modelled CLI text...")
    response = session.dispatch(et.fromstring(get_modelled_config_running))
    config = xmltodict.parse(response.xml)["rpc-reply"]["result"]
    cli_text = config["#text"]

    with open(output_file, 'w') as f:
        f.write('<config-ios-cli-trans xmlns ="http://cisco.com/ns/yang/Cisco-IOS-XE-cli-rpc">\n')
        f.write(' <clis>\n')
        f.write(cli_text)
        f.write('\n </clis>\n')
        f.write(' <operation>full-replace</operation>\n')
        f.write('  <do-commit>false</do-commit>\n')
        f.write('</config-ios-cli-trans>\n')

    print(f"Saved to '{output_file}'")
    print("Review and edit the file before using it with atomic_replace_config_v1.3.py.")


if __name__ == '__main__':
    session = netconf_connect(HOST, USERNAME, PASSWORD)
    try:
        get_running_as_target_xml(session, OUTPUT)
    finally:
        session.close_session()
        print("NETCONF session closed.")
