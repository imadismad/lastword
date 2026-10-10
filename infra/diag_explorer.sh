#!/usr/bin/env bash
# Diagnose explorer indexer vs API vs mongo
set +e
echo "=== CHAIN HEAD (eth_blockNumber) ==="
RPC="http://127.0.0.1:9650/ext/bc/2L6HsHiCxGeQFBoe5ezfz9ZBtNBZYGKC1QHrDCeQhLPYrW3iZj/rpc"
curl -s -m 8 -X POST -H 'content-type:application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' "$RPC"
echo
echo "=== MONGO: list collections + counts (lastword_explorer) ==="
sudo docker exec lastword-mongo mongosh lastword_explorer --quiet --eval '
  db.getCollectionNames().forEach(function(c){ print(c + " = " + db.getCollection(c).countDocuments()); });
'
echo "=== MONGO: sample block doc ==="
sudo docker exec lastword-mongo mongosh lastword_explorer --quiet --eval '
  var b = db.blocks.findOne(); printjson(b);
'
echo "=== API /blocks ==="
curl -s -m 8 http://127.0.0.1:3002/blocks | head -c 400
echo
echo "=== API /transactions ==="
curl -s -m 8 http://127.0.0.1:3002/transactions | head -c 400
echo
echo "=== Backend .env ==="
cat /home/ubuntu/explorer/backend/.env 2>/dev/null | sed 's/\(PRIVATE[^=]*=\).*/\1REDACTED/'
echo "=== indexer DB_NAME usage (grep) ==="
grep -rn "DB_NAME\|dbName\|lastword_explorer\|mongoose.connect\|createConnection" /home/ubuntu/explorer/backend/src /home/ubuntu/explorer/backend/periphery 2>/dev/null | head -40
echo "=== DONE ==="
