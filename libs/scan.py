#!/usr/bin/env python
"""
Scan library

Copyright 2020 Leboncoin
Licensed under the Apache License, Version 2.0
Written by Nicolas BEGUIER (nicolas.beguier@adevinta.com)
"""

# Standard library imports
import json
import logging

# Third party library imports
from botocore.config import Config

# Debug
# from pdb import set_trace as st

VERSION = '1.4.1'

LOGGER = logging.getLogger('aws-tower')

def get_tag(tags, key):
    names = [item['Value'] for item in tags if item['Key'] == key]
    if not names:
        return ''
    return names[0]

def draw_sg(security_group, sg_raw):
    result = ''
    for sg in sg_raw:
        if sg['GroupId'] != security_group:
            continue
        for ip_perm in sg['IpPermissions']:
            if ip_perm['IpProtocol'] not in ['tcp', '-1']:
                continue
            if ip_perm['IpProtocol'] == '-1':
                for group in ip_perm['UserIdGroupPairs']:
                    result += '{},'.format(group['GroupId'])
                for cidr in ip_perm['IpRanges']:
                    result += '{},'.format(cidr['CidrIp'])
                result = result[:-1] + '->All '
                continue
            from_port = ip_perm['FromPort']
            to_port = ip_perm['FromPort']
            ip_range = ip_perm['IpRanges']
            userid_group_pairs = ip_perm['UserIdGroupPairs']
            for group in userid_group_pairs:
                result += '{},'.format(group['GroupId'])
            for cidr in ip_range:
                result += '{},'.format(cidr['CidrIp'])
            result = result[:-1] + '=>{}'.format(from_port)
            if from_port != to_port:
                result += '-{}'.format(to_port)
            result += ' '
    return result[:-1]

def parse_report(report):
    """
    Return anomalies from report
    """
    new_report = dict()
    new_report['EC2'] = list()
    new_report['ELBV2'] = list()
    new_report['RDS'] = list()
    for vpc in report:
        for subnet in report[vpc]['Subnets']:
            mini_name = report[vpc]['Subnets'][subnet]['Name'].split('-{}'.format(
                report[vpc]['Subnets'][subnet]['AvailabilityZone']))[0]
            for ec2 in report[vpc]['Subnets'][subnet]['EC2']:
                report[vpc]['Subnets'][subnet]['EC2'][ec2].update({'Subnet Name': mini_name})
                new_report['EC2'].append(report[vpc]['Subnets'][subnet]['EC2'][ec2])
            for elbv2 in report[vpc]['Subnets'][subnet]['ELBV2']:
                report[vpc]['Subnets'][subnet]['ELBV2'][elbv2].update({'Subnet Name': mini_name})
                new_report['ELBV2'].append(report[vpc]['Subnets'][subnet]['ELBV2'][elbv2])
            for rds in report[vpc]['Subnets'][subnet]['RDS']:
                report[vpc]['Subnets'][subnet]['RDS'][rds].update({'Subnet Name': mini_name})
                new_report['RDS'].append(report[vpc]['Subnets'][subnet]['RDS'][rds])

    return new_report

def print_subnet(report, names_only=False):
    """
    Print subnets
    """
    new_report = dict()
    for vpc in report:
        new_report[vpc] = dict()
        for subnet in report[vpc]['Subnets']:
            mini_name = report[vpc]['Subnets'][subnet]['Name'].split('-{}'.format(
                report[vpc]['Subnets'][subnet]['AvailabilityZone']))[0]
            if not mini_name in new_report[vpc]:
                new_report[vpc][mini_name] = list()
            for ec2 in report[vpc]['Subnets'][subnet]['EC2']:
                ec2_report = report[vpc]['Subnets'][subnet]['EC2'][ec2]
                if names_only:
                    ec2_report = 'EC2: {}'.format(ec2_report['Name'])
                new_report[vpc][mini_name].append(ec2_report)
            for elbv2 in report[vpc]['Subnets'][subnet]['ELBV2']:
                elbv2_report = report[vpc]['Subnets'][subnet]['ELBV2'][elbv2]
                if names_only:
                    elbv2_report = 'ELBV2: {}'.format(elbv2_report['DNSName'])
                new_report[vpc][mini_name].append(elbv2_report)
            for rds in report[vpc]['Subnets'][subnet]['RDS']:
                rds_report = report[vpc]['Subnets'][subnet]['RDS'][rds]
                if names_only:
                    rds_report = 'RDS: {}'.format(rds_report['Name'])
                new_report[vpc][mini_name].append(rds_report)

    LOGGER.warning(json.dumps(new_report, sort_keys=True, indent=4))

def ec2_scan(
    boto_session,
    public_only=False,
    enable_ec2=True,
    enable_elbv2=True,
    enable_rds=True):
    """
    SCAN EC2
    """
    if not enable_ec2 and not enable_elbv2 and not enable_rds:
        enable_ec2 = True
        enable_elbv2 = True
        enable_rds = True
    config = Config(
        retries = dict(
            max_attempts = 10
        )
    )
    ec2_client = boto_session.client('ec2', config=config)
    vpcs_raw = ec2_client.describe_vpcs()['Vpcs']
    subnets_raw = ec2_client.describe_subnets()['Subnets']
    nacls_raw = ec2_client.describe_network_acls()['NetworkAcls']
    ec2_raw = ec2_client.describe_instances()['Reservations']
    sg_raw = ec2_client.describe_security_groups()['SecurityGroups']
    elbv2_client = boto_session.client('elbv2')
    load_balancers_raw = elbv2_client.describe_load_balancers()['LoadBalancers']
    rds_client = boto_session.client('rds')
    rds_raw = rds_client.describe_db_instances()['DBInstances']

    report = dict()

    for vpc in vpcs_raw:
        report[vpc['VpcId']] = dict()
        report[vpc['VpcId']]['Subnets'] = dict()
        report[vpc['VpcId']]['NetworkAcls'] = dict()

    for subnet in subnets_raw:
        subnet_name = 'Unknown'
        if 'Tags' in subnet:
            subnet_name = get_tag(subnet['Tags'], 'Name')
        report[subnet['VpcId']]['Subnets'][subnet['SubnetId']] = {
            'Name': subnet_name,
            'AvailabilityZone': subnet['AvailabilityZone'],
            'CidrBlock': subnet['CidrBlock']}
        report[subnet['VpcId']]['Subnets'][subnet['SubnetId']]['NetworkAcls'] = dict()
        report[subnet['VpcId']]['Subnets'][subnet['SubnetId']]['EC2'] = dict()
        report[subnet['VpcId']]['Subnets'][subnet['SubnetId']]['ELBV2'] = dict()
        report[subnet['VpcId']]['Subnets'][subnet['SubnetId']]['RDS'] = dict()

    for nacl in nacls_raw:
        if not nacl['Associations']:
            report[nacl['VpcId']]['NetworkAcls'][nacl['NetworkAclId']] = nacl['Entries']
        for nacl_assoc in nacl['Associations']:
            report[nacl['VpcId']]['Subnets'][nacl_assoc['SubnetId']]['NetworkAcls'][nacl['NetworkAclId']] = nacl['Entries']

    if enable_ec2:
        for ec2 in ec2_raw:
            for ec2_ in ec2['Instances']:
                if 'VpcId' in ec2_ and 'SubnetId' in ec2_:
                    if public_only and not 'PublicIpAddress' in ec2_:
                        continue
                    report[ec2_['VpcId']]['Subnets'][ec2_['SubnetId']]['EC2'][ec2_['InstanceId']] = dict()
                    report[ec2_['VpcId']]['Subnets'][ec2_['SubnetId']]['EC2'][ec2_['InstanceId']]['Type'] = 'EC2'
                    if 'Tags' in ec2_:
                        report[ec2_['VpcId']]['Subnets'][ec2_['SubnetId']]['EC2'][ec2_['InstanceId']]['Name'] = get_tag(ec2_['Tags'], 'Name')
                    else:
                        report[ec2_['VpcId']]['Subnets'][ec2_['SubnetId']]['EC2'][ec2_['InstanceId']]['Name'] = ec2_['InstanceId']
                    if 'PrivateIpAddress' in ec2_:
                        report[ec2_['VpcId']]['Subnets'][ec2_['SubnetId']]['EC2'][ec2_['InstanceId']]['PrivateIpAddress'] = ec2_['PrivateIpAddress']
                    if 'PublicIpAddress' in ec2_:
                        report[ec2_['VpcId']]['Subnets'][ec2_['SubnetId']]['EC2'][ec2_['InstanceId']]['PublicIpAddress'] = ec2_['PublicIpAddress']
                    if 'SecurityGroups' in ec2_:
                        for sg in ec2_['SecurityGroups']:
                            draw = draw_sg(sg['GroupId'], sg_raw)
                            if not draw:
                                continue
                            report[ec2_['VpcId']]['Subnets'][ec2_['SubnetId']]['EC2'][ec2_['InstanceId']][sg['GroupId']] = draw
                    # if 'ImageId' in ec2_:
                    #     report[ec2_['VpcId']]['Subnets'][ec2_['SubnetId']]['EC2'][ec2_['InstanceId']]['ImageId'] = ec2_['ImageId']

    if enable_elbv2:
        for elbv2 in load_balancers_raw:
            if public_only and elbv2['Scheme'] == 'internal':
                continue
            report[elbv2['VpcId']]['Subnets'][elbv2['AvailabilityZones'][0]['SubnetId']]['ELBV2'][elbv2['LoadBalancerName']] = dict()
            report[elbv2['VpcId']]['Subnets'][elbv2['AvailabilityZones'][0]['SubnetId']]['ELBV2'][elbv2['LoadBalancerName']]['Type'] = 'ELBV2'
            report[elbv2['VpcId']]['Subnets'][elbv2['AvailabilityZones'][0]['SubnetId']]['ELBV2'][elbv2['LoadBalancerName']]['Scheme'] = elbv2['Scheme']
            report[elbv2['VpcId']]['Subnets'][elbv2['AvailabilityZones'][0]['SubnetId']]['ELBV2'][elbv2['LoadBalancerName']]['DNSName'] = elbv2['DNSName']
            if 'SecurityGroups' in elbv2:
                for sg in elbv2['SecurityGroups']:
                    report[elbv2['VpcId']]['Subnets'][elbv2['AvailabilityZones'][0]['SubnetId']]['ELBV2'][elbv2['LoadBalancerName']][sg] = draw_sg(sg, sg_raw)

    if enable_rds:
        for rds in rds_raw:
            if public_only and not rds['PubliclyAccessible']:
                continue
            report[rds['DBSubnetGroup']['VpcId']]['Subnets'][rds['DBSubnetGroup']['Subnets'][0]['SubnetIdentifier']]['RDS'][rds['DBInstanceIdentifier']] = dict()
            report[rds['DBSubnetGroup']['VpcId']]['Subnets'][rds['DBSubnetGroup']['Subnets'][0]['SubnetIdentifier']]['RDS'][rds['DBInstanceIdentifier']]['Type'] = 'RDS'
            report[rds['DBSubnetGroup']['VpcId']]['Subnets'][rds['DBSubnetGroup']['Subnets'][0]['SubnetIdentifier']]['RDS'][rds['DBInstanceIdentifier']]['Name'] = rds['DBInstanceIdentifier']
            report[rds['DBSubnetGroup']['VpcId']]['Subnets'][rds['DBSubnetGroup']['Subnets'][0]['SubnetIdentifier']]['RDS'][rds['DBInstanceIdentifier']]['Address'] = rds['Endpoint']['Address']
            report[rds['DBSubnetGroup']['VpcId']]['Subnets'][rds['DBSubnetGroup']['Subnets'][0]['SubnetIdentifier']]['RDS'][rds['DBInstanceIdentifier']]['Engine'] = '{}=={}'.format(rds['Engine'], rds['EngineVersion'])
    return report
