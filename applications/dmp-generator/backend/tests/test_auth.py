def test_register_success(client):
    res = client.post("/api/auth/register", json={"username": "newuser", "password": "pass1234"})
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["username"] == "newuser"
    assert data["workspace"] == "user_newuser"


def test_register_duplicate(client):
    client.post("/api/auth/register", json={"username": "dup", "password": "pass1234"})
    res = client.post("/api/auth/register", json={"username": "dup", "password": "pass1234"})
    assert res.status_code == 409


def test_register_short_username(client):
    res = client.post("/api/auth/register", json={"username": "ab", "password": "pass1234"})
    assert res.status_code == 400


def test_register_short_password(client):
    res = client.post("/api/auth/register", json={"username": "validuser", "password": "12345"})
    assert res.status_code == 400


def test_login_success(client):
    client.post("/api/auth/register", json={"username": "logintest", "password": "test123"})
    res = client.post("/api/auth/login", json={"username": "logintest", "password": "test123"})
    assert res.status_code == 200
    assert "token" in res.json()


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"username": "logintest2", "password": "test123"})
    res = client.post("/api/auth/login", json={"username": "logintest2", "password": "wrong"})
    assert res.status_code == 401


def test_protected_route_no_token(client):
    res = client.get("/api/log/current")
    assert res.status_code == 403


def test_protected_route_with_token(client, auth_headers):
    res = client.get("/api/log/current", headers=auth_headers)
    assert res.status_code == 200
