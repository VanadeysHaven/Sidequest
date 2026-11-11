"""Domain services: every business operation, Discord-free (BRIEF §5.2, §5.6).

Call style: ``await todos.create_once(uow, actor, ...)``. Each function takes a `Uow`
(session + clock + config) and an `Actor`, checks permissions, commits its own work and
returns DTOs, never ORM objects. Mutations return an `Outcome` carrying effects for the
adapter (e.g. messages to delete) and whether the scheduler should wake up.

Locking: every write locks the to-do row (``SELECT … FOR UPDATE``) before touching its
occurrences or subtasks. The scheduler's `claim_due` locks to-do + occurrence with
``SKIP LOCKED``, so a user action and the scheduler never interleave on one to-do.
"""
