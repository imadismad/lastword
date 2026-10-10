# Run a remote command on the LASTWORD EC2 node without ever hanging the caller.
# Uses -n (stdin from NUL), BatchMode, and short timeouts. Writes output to a file.
param(
    [Parameter(Mandatory=$true)][string]$Cmd,
    [string]$OutFile = "C:\Users\Dell_Arte_III\Desktop\hackathon_essec_secure_horizon\ec2out.txt",
    [string]$HostIp = "13.223.184.99"
)
$pem = "C:\Users\Dell_Arte_III\Desktop\hackathon_essec_secure_horizon\infra\lastword-key.pem"
$sshArgs = @(
    "-n",
    "-i", $pem,
    "-o", "StrictHostKeyChecking=no",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=3",
    "ubuntu@$HostIp",
    $Cmd
)
& ssh @sshArgs *> $OutFile 2>&1
"EXITCODE=$LASTEXITCODE" | Out-File -Encoding utf8 -Append $OutFile
