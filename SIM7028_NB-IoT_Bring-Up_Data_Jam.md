# SIM7028 NB‑IoT Bring‑Up (Canonical – Data Jam)

This document captures **what actually solved** the NB‑IoT connectivity issue on the Atom DTU‑NB‑IoT2 (SIM7028) using Hologram SIMs in the US. This is the version to follow going forward.

---

## The Core Misunderstanding (Root Cause)

For SIM7028 **NB‑IoT** modules:

- **CID 0 is automatically created and activated by the modem**
- You are **not expected** to create or activate CID 1
- `AT+CGATT=1` and `AT+CEREG=5` **do NOT mean data is usable**
- **The IP data stack is closed by default**

👉 **Until `AT+NETOPEN` is issued, no IP traffic is possible**, even if the device is registered and attached.

This is why teams repeatedly saw:
- `pdn type and APN duplicate used`
- `AT+CGACT=1,1` failing
- SIMs blamed, bands blamed, roaming blamed

The modem was behaving correctly.

---

## What Actually Fixed the Issue

### 1. Flash AT Passthrough Firmware (Diagnostic Requirement)

Purpose:
- Remove all library logic and firmware interception
- Talk **directly** to the SIM7028

Result:
- Clean, deterministic AT responses
- Eliminated false assumptions caused by SDK behavior

> This step is **required for debugging**, not necessarily for production.

---

### 2. Optional but Recommended: Lock to US LTE Bands

```
AT+QCBAND=0,2,4,12,13,66
AT+CFUN=1,1
```

Why:
- Prevents the modem scanning unsupported global bands
- Reduces registration time
- Avoids long `CEREG: 2,2` loops

Important:
- **This improves convergence speed**
- **It is NOT the root cause fix**

---

### 3. Accept CID 0 (Do NOT Fight It)

Verify context state:
```
AT+CGDCONT?
AT+CGACT?
```

Expected:
```
+CGDCONT: 0,"IP","hologram"
+CGACT: 0,1
```

Rules:
- Do **not** attempt `AT+CGACT=1,1`
- Do **not** try to re‑authenticate CID 0
- Do **not** delete or override CID 0

CID 0 is the data context.

---

### 4. Attach to Packet Domain

```
AT+CGATT=1
```

Expected:
```
OK
```

This only confirms attachment — **not data readiness**.

---

### 5. **Critical Step: Open the Network Stack**

```
AT+NETOPEN
```

Expected:
```
+NETOPEN: 0
```

Without this command:
- No IP is allocated
- `AT+IPADDR` fails
- Device appears “stuck” despite registration

---

### 6. Verify IP Address

```
AT+IPADDR
```

Expected:
```
+IPADDR: 10.x.x.x
```

At this point, the device is **fully online**.

---

## Verification Commands (Ground Truth)

```
AT+CPSI?
```

Expected:
```
NB,Online,310-260,...,EUTRAN-BAND4
```

```
AT+CEREG?
```

Expected:
```
+CEREG: 2,5,...,9
```

---

## Key Lessons (Memorise These)

1. **CID 0 is the only PDP context you should use on SIM7028 NB‑IoT**
2. **`NETOPEN` is mandatory** — registration ≠ data
3. Band locking helps speed, not correctness
4. Vendor libraries obscure the real modem state
5. If `IPADDR` is empty, the network is not open — period

---

## One‑Line Mental Model

> *SIM7028 NB‑IoT does not give you IP just because you are registered. You must explicitly open the data plane.*
