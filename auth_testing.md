# Auth-Gated App Testing Playbook (Emergent Google Auth)

## Step 1: Create Test User & Session
```
mongosh --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: 'https://via.placeholder.com/150',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

## Step 2: Test Backend API
```
curl -X GET "$API_URL/api/auth/me" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

## Step 3: Browser Testing
```
await page.context.add_cookies([{
    "name": "session_token",
    "value": "YOUR_SESSION_TOKEN",
    "domain": "your-app.com",
    "path": "/",
    "httpOnly": true,
    "secure": true,
    "sameSite": "None"
}]);
```

## Checklist
- [ ] User has user_id field (UUID custom)
- [ ] Session user_id matches user's user_id
- [ ] All queries exclude `_id` with projection
- [ ] Backend uses user_id, not _id or id
- [ ] /api/auth/me returns user (no 401)
- [ ] Dashboard loads without redirect

## Success / Failure
- ✅ /api/auth/me returns user data
- ✅ Dashboard loads
- ❌ "User not found" or 401 means session/user linking is broken
