#!/usr/bin/env python
import os
import sys
import logging
import ConfigParser
from ConfigParser import NoOptionError
from templates.config import config_template

from starcluster import EC2

"""
Reads starcluster configuration settings defined in ~/.starclustercfg config file into starclustercfg module's namespace
"""

log = logging.getLogger('starcluster')


instance_types = {
    'm1.small':  'i386',
    'm1.large':  'x86_64',
    'm1.xlarge': 'x86_64',
    'c1.medium': 'i386',
    'c1.xlarge': 'x86_64',
}

def _get_int(config, section, option):
    try:
        opt = config.getint(section,option)
    except (NoOptionError):
        opt = None
    return opt

def _get_string(config, section, option):
    try:
        opt = config.get(section,option)
    except (NoOptionError):
        opt = None
    return opt

# setting, type, required?
ec2_options = [
    ('AWS_ACCESS_KEY_ID', _get_string, True),
    ('AWS_SECRET_ACCESS_KEY', _get_string, True),
    ('AWS_USERID', _get_string, True),
    ('KEYNAME', _get_string, True),
    ('KEY_LOCATION', _get_string, True),
]

starcluster_options = [
    ('MASTER_IMAGE_ID', _get_string, False),
    ('IMAGE_ID', _get_string, True),
    ('INSTANCE_TYPE', _get_string, False),
    ('AVAILABILITY_ZONE', _get_string, False),
    ('ATTACH_VOLUME', _get_string, False),
    ('VOLUME_DEVICE', _get_string, False),
    ('VOLUME_PARTITION', _get_string, False),
    ('DEFAULT_CLUSTER_SIZE', _get_int, True),
    ('CLUSTER_USER', _get_string, False)
]

sections = [
    ("section ec2", ec2_options),
    ("section starcluster", starcluster_options)
]

def load_settings():
    # TODO: create the template file for them
    if not os.path.exists(os.path.expanduser('~/.starclustercfg')):
        log.info('It appears this is your first time using StarCluster.')
        log.info('Please create $HOME/.starclustercfg using the template below:')
        print config_template
        sys.exit(1)

    config = ConfigParser.ConfigParser()
    config.read(os.path.expanduser('~/.starclustercfg'))

    for section in sections:
        section_name = section[0]; section_opts = section[1]
        for opt in section_opts:
            name = opt[0]; func = opt[1]; required = opt[2]
            value = func(config,section_name, name)
            globals()[name] = value

def is_valid():
    conn = _get_conn()

    if not _has_all_required_settings():
        log.error('Please specify the required settings in ~/.starclustercfg')
        return False

    if not _has_valid_credentials(conn):
        log.error('Invalid AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY combination')
        return False

    if not _has_keypair(conn, KEYNAME):
        log.error('Account does not contain a key with KEYNAME = %s. Please check your settings' % KEYNAME)
        return False
    
    if not os.path.exists(KEY_LOCATION):
        log.error('KEY_LOCATION=%s does not exist' % KEY_LOCATION)
        return False

    if not instance_types.has_key(INSTANCE_TYPE):
        log.error("""You specified an invalid INSTANCE_TYPE\nPossible options are:\n%s %s %s %s %s""" % tuple(instance_types.keys()))
        return False
    
    if DEFAULT_CLUSTER_SIZE <= 0:
        log.error('DEFAULT_CLUSTER_SIZE must be a positive integer')
        return False
    
    if CLUSTER_USER is None:
        log.warn('No CLUSTER_USER specified. Defaulting to sgeadmin user')
        globals()['CLUSTER_USER'] = 'sgeadmin'

    if not _has_valid_ebs_settings(conn):
        log.error('EBS settings are invalid, please check your settings')
        return False

    if not _has_valid_instance_type_settings(conn):
        log.error('Your INSTANCE_TYPE setting is invalid, please check your settings')
        return False

    if not _has_valid_image_settings(conn):
        log.error('Your MASTER_IMAGE_ID/IMAGE_ID setting(s) are invalid, please check your settings')
        return False

    if not _has_valid_availability_zone(conn):
        log.error('Your AVAILABILITY_ZONE setting is invalid, please check your settings')
        return False

    return True

def _has_valid_image_settings(conn):
    image = conn.describe_images(imageIds=[IMAGE_ID]).parse()
    if not image:
        log.error('IMAGE_ID %s does not exist' % IMAGE_ID)
        return False
    if MASTER_IMAGE_ID is not None:
        master_image = conn.describe_images(imageIds=[MASTER_IMAGE_ID]).parse()
        if not master_image:
            log.error('MASTER_IMAGE_ID %s does not exist' % MASTER_IMAGE_ID)
            return False
    return True

def _has_valid_availability_zone(conn):
    if AVAILABILITY_ZONE is not None:
        zone_list = conn.describe_availability_zones().parse()
        if not zone_list:
            log.error('No availability zones found')
            return False

        zones = {}
        for zone in zone_list:
            zones[zone[1]] = zone[2]

        if not zones.has_key(AVAILABILITY_ZONE):
            log.error('AVAILABILITY_ZONE = %s does not exist' % AVAILABILITY_ZONE)
            return False
        elif zones[AVAILABILITY_ZONE] != 'available':
            log.error('The AVAILABILITY_ZONE = %s is not available at this time')
            return False
    return True

def _has_valid_instance_type_settings(conn):
    image_platform = conn.describe_images(imageIds=[IMAGE_ID]).parse()[0][6]
    instance_platform = instance_types[INSTANCE_TYPE]
    if instance_platform != image_platform:
        log.error('You specified an incompatible IMAGE_ID and INSTANCE_TYPE')
        log.error('INSTANCE_TYPE = %(instance_type)s is for a %(instance_platform)s \
                    platform while IMAGE_ID = %(image_id)s is a %(image_platform)s' \
                    % { 'instance_type': INSTANCE_TYPE, 'instance_platform': instance_platform, \
                        'image_id': IMAGE_ID, 'image_platform': image_platform})
        return False
    
    if MASTER_IMAGE_ID is not None:
        master_image_platform = conn.describe_images(imageIds=[IMAGE_ID]).parse()[0][6]
        if instance_platform != master_image_platform:
            log.error('You specified an incompatible MASTER_IMAGE_ID and INSTANCE_TYPE')
            log.error('INSTANCE_TYPE = %(instance_type)s is for a %(instance_platform)s \
                        platform while MASTER_IMAGE_ID = %(master_image_id)s is a %(master_image_platform)s' \
                        % { 'instance_type': INSTANCE_TYPE, 'instance_platform': instance_platform, \
                            'image_id': MASETER_IMAGE_ID, 'image_platform': master_image_platform})
            return False
    
    return True

def _has_valid_ebs_settings(conn):
    #TODO check that ATTACH_VOLUME id exists
    if ATTACH_VOLUME is not None:
        vols = conn.describe_volumes(volumeIds=[ATTACH_VOLUME]).parse()
        if not vols:
            log.error('ATTACH_VOLUME = %s does not exist' % ATTACH_VOLUME)
            return False
        if VOLUME_DEVICE is None:
            log.error('Must specify VOLUME_DEVICE when specifying ATTACH_VOLUME setting')
            return False
        if VOLUME_PARTITION is None:
            log.error('Must specify VOLUME_PARTITION when specifying ATTACH_VOLUME setting')
            return False
    return True

def _has_all_required_settings():
    has_all_required = True
    for section in sections:
        section_name = section[0]; section_opts = section[1]
        for opt in section_opts:
            name = opt[0]; required = opt[2]
            if required and globals()[name] is None:
                log.warn('Missing rquired setting %s under section "%s"' % (name,section_name))
                has_all_required = False
    return has_all_required

def validate_or_exit():
    if not is_valid():
        log.error('configuration error...exiting')
        sys.exit(1)

def _get_conn():  
    return EC2.AWSAuthConnection(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)

def _has_valid_credentials(conn):
    return not conn.describe_instances().is_error

def _has_keypair(conn, keyname):
    keypairs = conn.describe_keypairs().parse()
    has_keypair = False
    for key in keypairs:
        if key[1] == KEYNAME:
            has_keypair = True
    return has_keypair
    
def _load_everything(config):
    for section in config.sections():
        for option in config.options(section):
            globals()[option.upper()] = config.get(section,option)

load_settings()