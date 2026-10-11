# HP — appairer nugget-3 et lancer la junction (pour Wanbl)

## Pourquoi ta branche `wanbl/badge-fw` ne suffit pas

Ta branche part de `6219eeb`, avant l'arrivée sur `main` de :
- `junction/mesh_junction.py` (le relais mesh → badge à faire tourner sur le HP),
- `infra/mesh_setup.py` et `infra/hp_nugget3.py` (configuration des nuggets).

À l'inverse, `main` n'avait pas ton PROVISION à 124 octets (`... || gatewayPub(64)`) : le bridge
du Dell envoyait 60 octets, que ton badge-sim et ton firmware refusent (`REFUSED`).
**C'est corrigé sur `main`** : le bridge envoie maintenant 124 octets, ton changement de
`badge_sim.py` et de `proto/SPEC.md` est repris tel quel, et les tests et attaques passent
(proto, bridge et agent : 38 OK ; e2e : 2/2 ; attaques : 5/5).

## 1. Récupérer le code

```powershell
git fetch origin
git checkout wanbl/badge-fw
git merge origin/main          # pas de conflit attendu : tes fichiers badge-fw/ ne touchent pas main
pip install meshtastic pyserial cryptography
```

## 2. Appairer nugget-3 (une seule commande)

Nugget-3 branché sur le HP :

```powershell
python infra/hp_nugget3.py --listen 30
```

Le script :
- détecte le port COM du nugget (puce CH34x, VID 1A86) ; si plusieurs sont branchés, ajoute `--port COMx` ;
- applique le canal LASTWORD (même PSK, EU_868, LONG_FAST, hop 3, offset de fréquence) ;
- relit la configuration pour vérifier ;
- écoute nugget-1 (Dell) et nugget-2 (relais) pendant 30 s.

N'utilise **pas** l'URL de canal d'une ancienne version de `junction/LIVE_DEMO.md` : elle
n'a pas l'offset de fréquence, et les nuggets ne s'entendraient pas. La bonne URL est
`https://meshtastic.org/e/#CgcSAQE6AggNEhQIATUAAKBBOANAA0gBUBtoAcAGAQ`.

## 3. Lancer la junction

**Test radio avec le badge logiciel** (HELLO / PROVISION seulement : le contrat porte
maintenant les clés de la vraie puce, donc ce badge ne peut pas payer) :

```powershell
python infra/hp_nugget3.py --run
```

Laisse tourner, puis préviens le Dell qu'il peut basculer le toggle **Real LoRa** de l'onglet
Live demo. La console de la junction doit afficher le PROVISION, puis les REQUEST.

**Ensuite avec ton vrai badge** (badge-fw sur USB, par exemple COM7) :

```powershell
python infra/hp_nugget3.py --run --badge serial:COM7
```

Le contrat EC2 (`0xc5a5…f5c42d`) a été mis à jour avec les clés **de la puce TROPIC01**
(STOCK `15129b0a…`, DAF `51b061f7…`). Le vrai badge signe donc on-chain ; en contrepartie,
`--badge sim` ne passe plus l'étape attest.

Quand la console affiche `REQUEST on the badge`, tu as **120 s** (`JUNCTION_APPROVE_S`)
pour lire l'e-paper puis faire **Y → PIN `123456` → Y**. Il y a deux REQUEST par
paiement : STOCK (attestation de livraison) puis DAF (approbation du paiement).

## Règles

- Un port COM ne peut être ouvert que par un seul programme à la fois. Ferme le client
  Meshtastic, `mesh_setup.py`, etc. avant de lancer la junction.
- Après un débranchement, le numéro de COM change ; le script le redétecte.
