# Database

PostgreSQL is the system of record. Migrations are applied in numeric order by a
release image; production startup must not retrieve migration tooling or packages
from the internet.

The initial schema establishes:

- Practice-local calendar policy and a rolling horizon
- Staff identities and roles
- Patients, doctors, procedures, rooms, and equipment
- Working hours, leave, closures, and patient availability
- Scheduling requests and model-normalized intake
- Appointment holds and confirmed appointments
- Scoped rescheduling permissions
- Appointment state history and append-only audit events
- Database-level overlap prevention for patients, doctors, and rooms

Database constraints are defense in depth. The API must still authorize every
operation, minimize PHI, record an audit event, and handle transaction conflicts.

