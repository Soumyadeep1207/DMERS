from app.search import search
GRID=[[1,1,1],[1,-1,1],[1,1,1]]
def test_all_algorithms_find_route():
    for name in ["bfs","dfs","ucs","greedy","astar"]:
        result=search(GRID,(0,0),(2,2),name)
        assert result.found and result.path[0] == (0,0) and result.path[-1] == (2,2)
