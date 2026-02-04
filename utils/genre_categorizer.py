#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genre categorization module for the markdown-to-podcast project.

Provides helpers to map detailed music genre strings into broader parent categories.
"""

from typing import Dict, List, Optional
import re


class GenreCategorizer:
    """Categorize music genres into higher level buckets."""

    def __init__(self):
        """Initialize with predefined mappings."""
        self.genre_mappings = {
            # Rock Genres
            "rock": [
                "alternative rock",
                "classic rock",
                "grunge",
                "hard rock",
                "indie rock",
                "post-punk",
                "psych-rock",
                "psychedelic rock",
                "punk",
                "rock",
                "rock n roll",
                "rock and roll",
                "rockabilly",
                "surf rock",
                "garage rock",
                "blues rock",
                "folk rock",
                "progressive rock",
                "art rock",
                "glam rock",
            ],
            # Metal Genres
            "metal": [
                "acoustic metal",
                "alternative metal",
                "ambient metal",
                "avant-garde metal",
                "black metal",
                "blackened death metal",
                "celtic metal",
                "chamber metal",
                "christian metal",
                "classic heavy metal",
                "cyber metal",
                "dark metal",
                "death metal",
                "doom metal",
                "experimental metal",
                "folk metal",
                "funeral doom metal",
                "gothic metal",
                "groove metal",
                "hair metal",
                "heavy metal",
                "horror metal",
                "industrial metal",
                "jazz metal",
                "math metal",
                "melodic death metal",
                "metalcore",
                "neo-classical metal",
                "new wave of british heavy metal",
                "nwobhm",
                "noise metal",
                "nu metal",
                "power metal",
                "post metal",
                "progressive metal",
                "screamo",
                "sludge metal",
                "speed metal",
                "stoner metal",
                "symphonic black metal",
                "symphonic metal",
                "technical death metal",
                "thrash metal",
                "viking metal",
            ],
            # Pop Genres
            "pop": [
                "acoustic pop",
                "cantopop",
                "indie-pop",
                "indie pop",
                "j-pop",
                "k-pop",
                "mandopop",
                "pop",
                "poprock",
                "pop rock",
                "power-pop",
                "power pop",
                "synth-pop",
                "synthpop",
                "electropop",
                "dance pop",
                "teen pop",
                "bubblegum pop",
            ],
            # Electronic & Dance
            "electronic": [
                "ambient",
                "bass music",
                "breakbeat",
                "chicago house",
                "chiptune",
                "club",
                "deep house",
                "detroit techno",
                "drum and bass",
                "dnb",
                "dubstep",
                "eurodance",
                "future bass",
                "garage",
                "hardstyle",
                "house",
                "j-dance",
                "minimal techno",
                "progressive house",
                "synthwave",
                "techno",
                "trance",
                "vaporwave",
                "edm",
                "electronic dance music",
                "big beat",
                "trip hop",
                "trip-hop",
            ],
            # Hip Hop & Urban
            "hip_hop": [
                "german rap",
                "deutschrap",
                "hip hop",
                "hip-hop",
                "rap",
                "trap",
                "gangsta rap",
                "conscious rap",
                "old school hip hop",
                "boom bap",
                "mumble rap",
                "cloud rap",
            ],
            # R&B & Soul
            "rnb_soul": [
                "r&b",
                "rnb",
                "soul",
                "neo soul",
                "contemporary r&b",
                "motown",
                "northern soul",
                "southern soul",
                "funk soul",
            ],
            # Jazz
            "jazz": [
                "acid jazz",
                "jazz",
                "jazz fusion",
                "smooth jazz",
                "swing",
                "bebop",
                "cool jazz",
                "free jazz",
                "hard bop",
                "latin jazz",
                "modal jazz",
                "post-bop",
                "ragtime",
                "big band",
            ],
            # Blues & Country
            "blues_country": [
                "blues",
                "bluegrass",
                "country",
                "delta blues",
                "chicago blues",
                "electric blues",
                "country blues",
                "alt-country",
                "country rock",
                "honky tonk",
                "western swing",
                "outlaw country",
            ],
            # Folk & World
            "folk_world": [
                "african music",
                "afrobeat",
                "balkan music",
                "caribbean music",
                "celtic music",
                "celtic",
                "folk",
                "indie folk",
                "indian music",
                "middle eastern music",
                "nordic folk",
                "krautrock",
                "world music",
                "traditional folk",
                "contemporary folk",
                "americana",
            ],
            # Latin & Caribbean
            "latin_caribbean": [
                "bachata",
                "bossa nova",
                "cumbia",
                "dancehall",
                "forró",
                "mambo",
                "merengue",
                "reggae",
                "reggaeton",
                "salsa",
                "samba",
                "sertanejo",
                "tango",
                "latin",
                "calypso",
                "son cubano",
                "bolero",
                "rumba",
            ],
            # Classical & Orchestral
            "classical": [
                "chamber music",
                "classical",
                "neo-classical",
                "neoclassical",
                "opera",
                "orchestral",
                "piano",
                "baroque",
                "romantic",
                "contemporary classical",
                "minimalism",
                "string quartet",
            ],
            # Alternative & Experimental
            "alternative_experimental": [
                "ambient",
                "avant-garde",
                "downtempo",
                "experimental",
                "industrial",
                "lo-fi",
                "lofi",
                "new age",
                "noise",
                "post hardcore",
                "post-hardcore",
                "shoegaze",
                "drone",
                "sound art",
                "musique concrète",
            ],
            # Funk & Groove
            "funk": ["funk", "groove", "p-funk", "funk rock", "funk metal", "acid funk", "go-go"],
            # Gospel & Christian
            "gospel_christian": [
                "christian metal",
                "gospel",
                "contemporary christian",
                "christian rock",
                "praise and worship",
                "southern gospel",
                "black gospel",
            ],
            # Reggae & Ska
            "reggae_ska": ["reggae", "ska", "rocksteady", "dub", "reggae fusion", "two tone", "third wave ska"],
            # Punk & Hardcore
            "punk_hardcore": [
                "punk",
                "hardcore punk",
                "post-punk",
                "pop punk",
                "pop-punk",
                "street punk",
                "crust punk",
                "anarcho-punk",
                "oi!",
                "post hardcore",
                "post-hardcore",
                "screamo",
            ],
        }

        # Reverse mapping for fast lookup
        self._create_reverse_mapping()

    def _create_reverse_mapping(self):
        """Create reverse mapping from genre -> category."""
        self.reverse_mapping = {}
        for category, genres in self.genre_mappings.items():
            for genre in genres:
                self.reverse_mapping[genre.lower()] = category

    def categorize_genre(self, genre: str) -> Optional[str]:
        """Categorize a single genre.

        Args:
            genre: raw genre string

        Returns:
            Parent category or None if not found.
        """
        if not genre:
            return None

        genre_clean = self._clean_genre_name(genre)

        # Direct lookup
        if genre_clean in self.reverse_mapping:
            return self.reverse_mapping[genre_clean]

        # Fuzzy matching for close variants
        return self._fuzzy_match(genre_clean)

    def _clean_genre_name(self, genre: str) -> str:
        """Normalize / clean a genre string for matching."""
        genre = genre.lower().strip()
        # Remove special characters
        genre = re.sub(r"[^\w\s-]", "", genre)
        # Normalize whitespace
        genre = re.sub(r"\s+", " ", genre)
        return genre

    def _fuzzy_match(self, genre: str) -> Optional[str]:
        """Attempt heuristic fuzzy matching for unknown genres."""
        # Substring search among known genres
        for known_genre, category in self.reverse_mapping.items():
            # Check if either is a substring of the other
            if genre in known_genre or known_genre in genre:
                return category

        # Heuristic fallbacks for common tokens
        if "metal" in genre:
            return "metal"
        elif "rock" in genre:
            return "rock"
        elif "pop" in genre:
            return "pop"
        elif "jazz" in genre:
            return "jazz"
        elif "electronic" in genre or "dance" in genre or "house" in genre:
            return "electronic"
        elif "hip" in genre or "rap" in genre:
            return "hip_hop"
        elif "folk" in genre:
            return "folk_world"
        elif "classical" in genre or "orchestra" in genre:
            return "classical"
        elif "punk" in genre:
            return "punk_hardcore"
        elif "blues" in genre:
            return "blues_country"
        elif "country" in genre:
            return "blues_country"
        elif "reggae" in genre:
            return "reggae_ska"
        elif "funk" in genre:
            return "funk"

        return None

    def categorize_multiple_genres(self, genres: List[str]) -> Dict[str, str]:
        """Categorize multiple genres.

        Args:
            genres: list of genre names

        Returns:
            Mapping genre -> category
        """
        result = {}
        for genre in genres:
            category = self.categorize_genre(genre)
            if category:
                result[genre] = category
        return result

    def get_genres_by_category(self, category: str) -> List[str]:
        """Return all genres belonging to a category."""
        return self.genre_mappings.get(category, [])

    def get_all_categories(self) -> List[str]:
        """Return list of all available categories."""
        return list(self.genre_mappings.keys())

    def get_category_stats(self, genres: List[str]) -> Dict[str, int]:
        """Compute category frequency stats for a list of genres."""
        stats = {}
        for genre in genres:
            category = self.categorize_genre(genre)
            if category:
                stats[category] = stats.get(category, 0) + 1
        return stats


def main():
    """Example usage when run as a script."""
    categorizer = GenreCategorizer()

    # Demo test set
    test_genres = [
        "Rock",
        "Heavy Metal",
        "Pop",
        "Hip Hop",
        "Jazz",
        "Death Metal",
        "Alternative Rock",
        "Techno",
        "Blues",
        "Progressive Metal",
        "Indie Pop",
        "Drum and Bass",
    ]

    print("Genre categorization test:")
    print("=" * 50)

    for genre in test_genres:
        category = categorizer.categorize_genre(genre)
        print(f"{genre:20} -> {category}")

    print("\nCategory statistics:")
    print("=" * 50)
    stats = categorizer.get_category_stats(test_genres)
    for category, count in sorted(stats.items()):
        print(f"{category:20}: {count} Genres")


if __name__ == "__main__":
    main()
