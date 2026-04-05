/**
 * Error helper utilities
 *
 * Standardized error response format for the API.
 * TODO: Make sure all routes actually use these helpers
 * instead of manually constructing error objects.
 */

function createError(status, message) {
  return {
    error: message,
    status: status
  };
}

function notFound(resource) {
  return createError(404, `${resource} not found`);
}

function badRequest(message) {
  return createError(400, message || 'Bad request');
}

function unauthorized(message) {
  return createError(401, message || 'Unauthorized');
}

module.exports = {
  createError,
  notFound,
  badRequest,
  unauthorized
};
