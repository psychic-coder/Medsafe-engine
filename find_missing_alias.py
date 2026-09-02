import csv
import subprocess

norm_strings = set()
with open('data/processed/alias_bridge_table_final.csv') as f:
    for r in csv.DictReader(f):
        norm_strings.add(r['normalized_string'])

res = subprocess.run([
    "docker", "exec", "medsafe-neo4j", "cypher-shell", "-u", "neo4j", "-p", "changeme_local_only",
    "--format", "plain",
    "MATCH (a:Alias) RETURN count(a)"
], capture_output=True, text=True)
print("Count in Neo4j:", res.stdout.strip())

neo4j_aliases = set()
res = subprocess.run([
    "docker", "exec", "medsafe-neo4j", "cypher-shell", "-u", "neo4j", "-p", "changeme_local_only",
    "--format", "csv",
    "MATCH (a:Alias) RETURN a.normalized_string"
], capture_output=True, text=True)

for line in res.stdout.splitlines()[1:]:
    val = line.strip().strip('"')
    neo4j_aliases.add(val)

print("Unique collected from Cypher:", len(neo4j_aliases))
missing = norm_strings - neo4j_aliases
print("Missing:", missing)

