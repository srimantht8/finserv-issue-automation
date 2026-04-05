const express = require('express');
const bcrypt = require('bcryptjs');
const router = express.Router();

// In-memory user store (fake DB)
const users = [
  {
    id: 1,
    email: 'admin@finserv.com',
    password: '$2a$10$XQxBj1MFG.5JnGXShYrSyOzEN0egMDvlRMPqM0C1rXKc8IJvZ3EXq', // "admin123"
    role: 'admin',
    name: 'Admin User'
  }
];

let nextId = 2;

// POST /login
router.post('/login', function(req, res) {
  var email = req.body.email;
  var password = req.body.password;

  if (!email || !password) {
    return res.status(400).json({ error: 'Email and password are required' });
  }

  var user = users.find(function(u) { return u.email === email; });

  if (!user) {
    return res.status(401).json({ error: 'Invalid credentials' });
  }

  bcrypt.compare(password, user.password, function(err, match) {
    if (err) {
      return res.status(500).json({ error: 'Internal server error' });
    }
    if (!match) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    req.session.userId = user.id;
    req.session.email = user.email;
    req.session.role = user.role;

    res.json({
      message: 'Login successful',
      user: { id: user.id, email: user.email, name: user.name, role: user.role }
    });
  });
});

// POST /register
router.post('/register', function(req, res) {
  var email = req.body.email;
  var password = req.body.password;
  var name = req.body.name;

  if (!email || !password || !name) {
    return res.status(400).json({ error: 'Email, password, and name are required' });
  }

  var existing = users.find(function(u) { return u.email === email; });
  if (existing) {
    return res.status(409).json({ error: 'User already exists' });
  }

  bcrypt.hash(password, 10, function(err, hash) {
    if (err) {
      return res.status(500).json({ error: 'Failed to hash password' });
    }

    var newUser = {
      id: nextId++,
      email: email,
      password: hash,
      role: 'user',
      name: name
    };

    users.push(newUser);

    req.session.userId = newUser.id;
    req.session.email = newUser.email;

    res.status(201).json({
      message: 'User registered',
      user: { id: newUser.id, email: newUser.email, name: newUser.name }
    });
  });
});

// POST /change-password
// BUG: Does not invalidate other existing sessions after password change.
// Only updates the password in the store — any other active sessions for
// this user remain valid with the old session cookie.
router.post('/change-password', function(req, res) {
  if (!req.session.userId) {
    return res.status(401).json({ error: 'Not authenticated' });
  }

  var currentPassword = req.body.currentPassword;
  var newPassword = req.body.newPassword;

  if (!currentPassword || !newPassword) {
    return res.status(400).json({ error: 'Current password and new password are required' });
  }

  var user = users.find(function(u) { return u.id === req.session.userId; });
  if (!user) {
    return res.status(404).json({ error: 'User not found' });
  }

  bcrypt.compare(currentPassword, user.password, function(err, match) {
    if (err) {
      return res.status(500).json({ error: 'Internal server error' });
    }
    if (!match) {
      return res.status(401).json({ error: 'Current password is incorrect' });
    }

    bcrypt.hash(newPassword, 10, function(err, hash) {
      if (err) {
        return res.status(500).json({ error: 'Failed to hash new password' });
      }

      // Update password in store
      user.password = hash;

      // NOTE: We do NOT invalidate other sessions here.
      // The current session stays active, but any other sessions
      // (e.g. on other devices) also remain valid.
      // This should destroy all other sessions for this user.

      res.json({ message: 'Password changed successfully' });
    });
  });
});

// POST /logout
router.post('/logout', function(req, res) {
  req.session.destroy(function(err) {
    if (err) {
      return res.status(500).json({ error: 'Failed to logout' });
    }
    res.json({ message: 'Logged out successfully' });
  });
});

// Export the users array so other modules can access it
router.getUsers = function() {
  return users;
};

module.exports = router;
