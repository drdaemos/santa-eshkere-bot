"""Secret Santa assignment generation algorithm"""

import random
from typing import List, Tuple

from ..database.models import User, Exclusion


class AssignmentGenerator:
    """Generate Secret Santa assignments with exclusion rules"""

    @staticmethod
    def generate_assignments(
        participants: List[User],
        exclusions: List[Exclusion]
    ) -> List[Tuple[int, int]]:
        """
        Generate Secret Santa assignments using backtracking algorithm.

        Args:
            participants: List of User objects who are participating
            exclusions: List of Exclusion objects defining forbidden pairs

        Returns:
            List of (giver_id, receiver_id) tuples

        Raises:
            ValueError: If no valid assignment exists
        """
        if len(participants) < 3:
            raise ValueError("Need at least 3 participants for Secret Santa")

        # Build forbidden pairs set (bidirectional + self)
        forbidden = set()

        # Add self-assignments as forbidden
        for user in participants:
            forbidden.add((user.id, user.id))

        # Add exclusion rules (bidirectional)
        for exclusion in exclusions:
            forbidden.add((exclusion.user1_id, exclusion.user2_id))
            forbidden.add((exclusion.user2_id, exclusion.user1_id))

        participant_ids = [user.id for user in participants]

        # Use backtracking to find valid assignment
        result = AssignmentGenerator._backtrack_assign(
            participant_ids,
            forbidden,
            [],
            set()
        )

        if result is None:
            raise ValueError(
                "No valid assignment found. "
                "Too many exclusion rules or impossible configuration."
            )

        return result

    @staticmethod
    def _backtrack_assign(
        participant_ids: List[int],
        forbidden: set,
        current_assignment: List[Tuple[int, int]],
        assigned_receivers: set
    ) -> List[Tuple[int, int]] | None:
        """
        Recursive backtracking to build valid assignment.

        Args:
            participant_ids: List of all participant IDs
            forbidden: Set of forbidden (giver_id, receiver_id) pairs
            current_assignment: Current partial assignment
            assigned_receivers: Set of receiver IDs already assigned

        Returns:
            Complete valid assignment or None if impossible
        """
        # Base case: all participants assigned
        if len(current_assignment) == len(participant_ids):
            return current_assignment

        # Get next giver to assign
        giver_id = participant_ids[len(current_assignment)]

        # Try receivers in random order for variety
        available_receivers = [
            r for r in participant_ids
            if r not in assigned_receivers
        ]
        random.shuffle(available_receivers)

        for receiver_id in available_receivers:
            # Check if this assignment is valid
            if (giver_id, receiver_id) in forbidden:
                continue

            # Try this assignment
            new_assignment = current_assignment + [(giver_id, receiver_id)]
            new_assigned = assigned_receivers | {receiver_id}

            # Recurse
            result = AssignmentGenerator._backtrack_assign(
                participant_ids,
                forbidden,
                new_assignment,
                new_assigned
            )

            if result is not None:
                return result

        # No valid assignment found with this path
        return None

    @staticmethod
    def validate_can_assign(
        participant_count: int,
        exclusions: List[Exclusion]
    ) -> bool:
        """
        Quick validation to check if assignment is likely possible.

        This is a heuristic check, not a guarantee.
        """
        if participant_count < 3:
            return False

        # Simple heuristic: if exclusions >= participants, likely impossible
        # (This is not perfect but catches obvious cases)
        if len(exclusions) >= participant_count:
            return False

        return True
