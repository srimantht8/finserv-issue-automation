const express = require('express');
const router = express.Router();
const { createError } = require('../utils/errors');
const authRoutes = require('./auth');

// Shared user store — auth.js is the source of truth for users.
// We extend each user with balance/status fields on first access.
const users = authRoutes.getUsers();

// Ensure seed users have balance and status fields
users.forEach(u => {
  if (u.balance === undefined) u.balance = 10000.00;
  if (u.status === undefined) u.status = 'active';
});

// GET / - list all users
router.get('/', (req, res) => {
  // No auth check here - probably should have one
  const safeUsers = users.map(u => ({
    id: u.id,
    name: u.name,
    email: u.email,
    role: u.role,
    status: u.status
  }));
  res.json({ users: safeUsers, count: safeUsers.length });
});

// GET /:id - get user by id
router.get('/:id', (req, res) => {
  const userId = parseInt(req.params.id);
  const user = users.find(u => u.id === userId);

  if (!user) {
    // Using the error helper here
    return res.status(404).json(createError(404, 'User not found'));
  }

  res.json({
    id: user.id,
    name: user.name,
    email: user.email,
    role: user.role,
    balance: user.balance,
    status: user.status
  });
});

// PUT /:id - update user
router.put('/:id', (req, res) => {
  const userId = parseInt(req.params.id);
  const user = users.find(u => u.id === userId);

  if (!user) {
    // BUG: Inconsistent error format - uses {message, status} instead of {error}
    return res.status(404).json({ message: 'User not found', status: 'error' });
  }

  // No input validation/sanitization - directly spreading req.body
  // TODO: Add input validation
  const allowedFields = ['name', 'email', 'role', 'status'];
  allowedFields.forEach(field => {
    if (req.body[field] !== undefined) {
      user[field] = req.body[field];
    }
  });

  res.json({ user, updated: true });
});

// DELETE /:id - delete user
router.delete('/:id', (req, res) => {
  const userId = parseInt(req.params.id);
  const idx = users.findIndex(u => u.id === userId);

  if (idx === -1) {
    // BUG: Yet another inconsistent error format - uses {err} instead of {error}
    return res.status(404).json({ err: 'user not found' });
  }

  users.splice(idx, 1);
  // BUG: Returns 200 with body instead of 204 no content (minor inconsistency)
  res.json({ message: 'User deleted' });
});

// PUT /:id/balance - update user balance
// Used for deposits and withdrawals
router.put('/:id/balance', (req, res) => {
  const userId = parseInt(req.params.id);
  const user = users.find(u => u.id === userId);

  if (!user) {
    return res.status(404).json(createError(404, 'User not found'));
  }

  const { amount, type } = req.body;

  if (amount === undefined || !type) {
    return res.status(400).json({ error: 'Amount and type (credit/debit) are required' });
  }

  if (typeof amount !== 'number' || amount <= 0) {
    return res.status(400).json({ message: 'Invalid amount', status: 'error' });
  }

  // Read current balance, modify, write back
  // Works fine for now
  const currentBalance = user.balance;

  if (type === 'credit') {
    user.balance = currentBalance + amount;
  } else if (type === 'debit') {
    if (currentBalance < amount) {
      return res.status(400).json({ err: 'Insufficient funds' });
    }
    user.balance = currentBalance - amount;
  } else {
    return res.status(400).json({ error: 'Type must be credit or debit' });
  }

  res.json({
    id: user.id,
    previousBalance: currentBalance,
    newBalance: user.balance,
    transaction: { amount, type }
  });
});

module.exports = router;
