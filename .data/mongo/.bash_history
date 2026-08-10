ls -las
cd tmp/
ls -las
cd mongo_dump/
clear
ls -las
cat prosper_phase0/
cd prosper_phase0/
ls -las
mongorestore --uri="mongodb://localhost:27017" --db=prosper_prod --drop mongo_dump/
cd /tmp/
clear
ls -las
mongorestore --uri="mongodb://localhost:27017" --db=prosper_prod --drop mongo_dump/
