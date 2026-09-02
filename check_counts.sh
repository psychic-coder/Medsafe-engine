docker exec medsafe-neo4j cypher-shell -u neo4j -p changeme_local_only "MATCH (n) RETURN labels(n)[0] AS label, count(n) ORDER BY label;"
docker exec medsafe-neo4j cypher-shell -u neo4j -p changeme_local_only "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) ORDER BY rel_type;"
