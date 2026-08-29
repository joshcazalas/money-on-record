[
  .resource_changes[]?
  | select(.change.actions != ["no-op"])
  | select(.change.actions != ["read"])
  | {
      address,
      actions: .change.actions,
      scope: $environment
    }
]
