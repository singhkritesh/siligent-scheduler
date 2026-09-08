SILIGENT SCHEDULER - WINDOWS INSTALLATION

Connected installation (Administrator PowerShell):

  .\deploy\windows\install.ps1 -Connected -Yes

Offline signed-bundle installation:

  .\deploy\windows\install.ps1 -Offline

The deterministic rules profile is the default and does not install Ollama.
Use -WithLocalModel only when local AI assistance is approved.

Daily operations:

  .\deploy\windows\start.ps1
  .\deploy\windows\verify.ps1
  .\deploy\windows\stop.ps1

The Windows entry points use the same checked Bash lifecycle as macOS and Linux
so installation, configuration, database preservation, and health behavior do
not diverge by platform. Docker Desktop and Git for Windows are installed with
winget during a connected installation when missing. Normal runtime performs no
downloads and uses Docker Compose with pulling disabled.

The optional network-policy.ps1 command changes Docker Desktop-wide outbound
firewall behavior and therefore requires administrator/IT approval. Block mode
rolls back its newly created rules if the application egress test fails.

Production use additionally requires practice-approved TLS, encrypted storage,
backup restoration testing, unique accounts, host security controls, and the
organizational safeguards described in PRODUCTION_READINESS.md.
