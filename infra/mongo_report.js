// Report explorer DB state: counts + the LASTWORD payment txs (contract calls)
print("=== COUNTS ===");
print("blocks=" + db.blocks.countDocuments());
print("transactions=" + db.transactions.countDocuments());
print("=== LATEST 15 BLOCKS (number -> #txs) ===");
db.blocks.find({}, {number:1, hash:1, transactions:1}).sort({number:-1}).limit(15).forEach(function(b){
  var n = (b.transactions && b.transactions.length) || 0;
  print("block #" + b.number + "  txs=" + n + "  " + (b.hash||""));
});
print("=== TRANSACTIONS (hash | from->to | value | method | status) ===");
db.transactions.find().sort({blockNumber:-1}).limit(30).forEach(function(t){
  print("blk#" + t.blockNumber + " " + (t.hash||"").slice(0,18) + ".. " +
        (t.from||"").slice(0,10) + "->" + (t.to? t.to.slice(0,10):"CREATE") +
        " val=" + t.value + " method=" + (t.method||"-") + " status=" + t.status);
});
