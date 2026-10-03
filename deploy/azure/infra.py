"""Generate the two-host ARM deployment without embedding credentials."""
import json
from pathlib import Path


def template():
    resources=[]
    def add(type,name,properties,depends=(),**extra):
        resources.append(dict(type=type,apiVersion='2024-03-01' if type.startswith('Microsoft.Network/') else '2024-07-01',name=name,location='[resourceGroup().location]',properties=properties,dependsOn=list(depends),**extra))
    for role in ['web','worker']:
        rules=[dict(name='OperatorSSH',properties=dict(priority=100,protocol='Tcp',access='Allow',direction='Inbound',sourceAddressPrefix='[parameters(\'operatorCidr\')]',sourcePortRange='*',destinationAddressPrefix='*',destinationPortRange='22'))]
        if role=='web':
            rules += [dict(name='HTTPS',properties=dict(priority=110,protocol='Tcp',access='Allow',direction='Inbound',sourceAddressPrefix='Internet',sourcePortRange='*',destinationAddressPrefix='*',destinationPortRanges=['80','443']))]
        else:
            rules += [dict(name='PrivateExecutor',properties=dict(priority=110,protocol='Tcp',access='Allow',direction='Inbound',sourceAddressPrefix='10.42.1.4',sourcePortRange='*',destinationAddressPrefix='10.42.2.4',destinationPortRange='8094'))]
        rules += [dict(name='DenyOtherInbound',properties=dict(priority=4000,protocol='*',access='Deny',direction='Inbound',sourceAddressPrefix='*',sourcePortRange='*',destinationAddressPrefix='*',destinationPortRange='*'))]
        add('Microsoft.Network/networkSecurityGroups','rescue-'+role+'-nsg',dict(securityRules=rules))
        add('Microsoft.Network/publicIPAddresses','rescue-'+role+'-ip',dict(publicIPAllocationMethod='Static',publicIPAddressVersion='IPv4',dnsSettings=dict(domainNameLabel="[concat(parameters('dnsPrefix'), '-"+role+"')]")),sku=dict(name='Standard'))
    add('Microsoft.Network/virtualNetworks','rescue-network',dict(addressSpace=dict(addressPrefixes=['10.42.0.0/16']),subnets=[dict(name=role,properties=dict(addressPrefix=f'10.42.{i}.0/24',networkSecurityGroup=dict(id=f"[resourceId('Microsoft.Network/networkSecurityGroups', 'rescue-{role}-nsg')]"))) for i,role in enumerate(['web','worker'],1)]),[f"[resourceId('Microsoft.Network/networkSecurityGroups', 'rescue-{role}-nsg')]" for role in ['web','worker']])
    for i,role in enumerate(['web','worker'],1):
        add('Microsoft.Network/networkInterfaces','rescue-'+role+'-nic',dict(ipConfigurations=[dict(name='primary',properties=dict(privateIPAllocationMethod='Static',privateIPAddress=f'10.42.{i}.4',subnet=dict(id=f"[resourceId('Microsoft.Network/virtualNetworks/subnets','rescue-network','{role}')]"),publicIPAddress=dict(id=f"[resourceId('Microsoft.Network/publicIPAddresses','rescue-{role}-ip')]")))]),["[resourceId('Microsoft.Network/virtualNetworks','rescue-network')]",f"[resourceId('Microsoft.Network/publicIPAddresses','rescue-{role}-ip')]"])
        add('Microsoft.Compute/virtualMachines','rescue-'+role,dict(hardwareProfile=dict(vmSize="[parameters('vmSize')]"),osProfile=dict(computerName='rescue-'+role,adminUsername='rescueadmin',customData="[base64(parameters('cloudInit'))]",linuxConfiguration=dict(disablePasswordAuthentication=True,ssh=dict(publicKeys=[dict(path='/home/rescueadmin/.ssh/authorized_keys',keyData="[parameters('sshPublicKey')]")]))),storageProfile=dict(imageReference=dict(publisher='Canonical',offer='ubuntu-24_04-lts',sku='server',version='latest'),osDisk=dict(createOption='FromImage',diskSizeGB=64,managedDisk=dict(storageAccountType='StandardSSD_LRS'),deleteOption='Delete')),networkProfile=dict(networkInterfaces=[dict(id=f"[resourceId('Microsoft.Network/networkInterfaces','rescue-{role}-nic')]",properties=dict(primary=True))])),[f"[resourceId('Microsoft.Network/networkInterfaces','rescue-{role}-nic')]"])
    return dict(**{'$schema':'https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#','contentVersion':'1.0.0.0'},parameters={name:dict(type='string',**({'defaultValue':'Standard_B2ls_v2'} if name=='vmSize' else {})) for name in ['operatorCidr','dnsPrefix','sshPublicKey','cloudInit','vmSize']},resources=resources)

if __name__=='__main__':
    target=Path(__file__).with_name('main.json');target.write_text(json.dumps(template(),indent=2)+'\n');print(target)
