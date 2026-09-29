"""Bilan des pronostics effectivement envoyes ; rapports officiels uniquement.
Les anciennes simulations P1/V2A/V2N restent dans l'historique Git, mais ne
sont plus executees ni melangees au bilan des conseils Telegram.
"""
import logging
from pmu_tracking import main

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(),
                        logging.FileHandler('pmu_results.log', encoding='utf-8')])
    main()
