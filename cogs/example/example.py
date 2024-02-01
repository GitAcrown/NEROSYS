# Module d'exemple commenté où on va faire en sorte que le bot réponde à des messages qu'on lui envoie

import logging
from datetime import datetime

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from common import dataio
from common.utils import fuzzy

# On définit un logger, ça va servir à renvoyer proprement les erreurs pour facilement les retrouver
logger = logging.getLogger(f'NEROSYS.{__name__.split(".")[-1]}')

# On crée la classe du module, qui doit hériter de commands.Cog et qui porte généralement le même nom que le fichier
class Example(commands.Cog):
    """Module d'exemple : gestionnaire de triggers personnalisés""" # Cette description est affichée dans la commande d'aide
    def __init__(self, bot: commands.Bot):
        self.bot = bot # On récupère l'instance du bot
        self.data = dataio.get_instance(self) # On récupère l'instance de dataio qui va gérer les données de ce module et les organiser tout seul dans un sous-dossier 'data' dans le dossier du module
        
        # Vu qu'on veut des paramètres, on en définit par défaut
        # Les paramètres sont stockés sous la forme d'un dictionnaire str: str donc faut que tous les paramètres puissent être convertis en str facilement
        default_settings = {
            'enabled': 1, # Un paramètre enabled qui décide si la fonctionnalité est activée ou non
            'cooldown': 5 # Un paramètre cooldown qui définit le cooldown entre chaque réponse en secondes
        }
        # Vu que les paramètres sont sous la forme simplifiée clef/valeur, on peut utiliser une déclaration de table dataio DictTable
        settings = dataio.DictTableDefault('settings', default_settings) # Voir common/dataio.py pour plus d'infos
        
        # On va faire une autre table pour stocker les messages de réponse
        # Cette fois on va utiliser une table dataio Table, ce qui nécessite de créer manuellement la table et donc de connaître un peu de SQL
        messages = dataio.TableDefault("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger TEXT,
            response TEXT,
            author_id INTEGER
            )""")
        # Vu qu'on veut que ces données soient stockées par serveur, on va les déclarer comme tables de fichiers serveurs
        self.data.set_defaults(discord.Guild, settings, messages)
        
        self.__cooldowns : dict[int, dict[int, float]] = {} # On va stocker les cooldowns dans un dictionnaire sur la RAM sous la forme {guild_id: {user_id: cooldown}}
        
    def cog_unload(self): # Il est conseillé de toujours définir cette fonction pour fermer self.data et éviter les fuites mémoire
        self.data.close_all()
    
    # FONCTIONS DE GESTION DES PARAMÈTRES ========================
    
    def is_enabled(self, guild: discord.Guild) -> bool:
        """Vérifie si la fonctionnalité est activée sur le serveur"""
        # Vu que la table de paramètres une table DictTable, on peut utiliser les raccourcis get_dict_value et set_dict_value pour accéder aux paramètres (v. common/dataio.py)
        return self.data.get(guild).get_dict_value('settings', 'enabled', cast=bool) # On cast en bool pour obtenir un booléen
    
    def set_enabled(self, guild: discord.Guild, enabled: bool) -> None:
        """Active ou désactive la fonctionnalité sur le serveur"""
        self.data.get(guild).set_dict_value('settings', 'enabled', enabled) # On utilise set_dict_value pour modifier les paramètres
        
    def get_guild_cooldown(self, guild: discord.Guild) -> int:
        """Renvoie le cooldown en secondes"""
        return self.data.get(guild).get_dict_value('settings', 'cooldown', cast=int)
    
    def set_guild_cooldown(self, guild: discord.Guild, cooldown: int) -> None:
        """Définit le cooldown en secondes"""
        self.data.get(guild).set_dict_value('settings', 'cooldown', cooldown)
        
    # FONCTIONS DE GESTION DES MESSAGES ==========================
    
    def get_messages(self, guild: discord.Guild) -> list[dict[str, str]]:
        """Renvoie la liste des messages de réponse"""
        # Là il faut savoir utiliser SQL pour récupérer les données vu que ce n'est pas un simple dictionnaire
        r = self.data.get(guild).fetch_all('SELECT * FROM messages') # On utilise fetch_all pour exécuter une requête SQL et récupérer tous les résultats
        return r if r else []
    
    def add_message(self, guild: discord.Guild, trigger: str, response: str, author_id: int) -> None:
        """Ajoute un message de réponse"""
        # On utilise execute pour exécuter une requête SQL sans récupérer de résultat
        self.data.get(guild).execute('INSERT INTO messages (trigger, response, author_id) VALUES (?, ?, ?)', (trigger, response, author_id))
        
    def remove_message(self, guild: discord.Guild, id: int) -> None:
        """Supprime un message de réponse"""
        self.data.get(guild).execute('DELETE FROM messages WHERE id = ?', (id,))
        
    # COMMANDES ===================================================
    
    # On va créer un groupe de commandes pour gérer les paramètres (serveur uniquement, par défaut accessible seulement aux modérateurs)
    config_group = app_commands.Group(name='config-trig', description="Gestion des paramètres du module d'exemple de triggers", guild_only=True, default_permissions=discord.Permissions(manage_messages=True))

    @config_group.command(name='enable')
    @app_commands.rename(enabled='activé') # On peut renommer les paramètres pour le support de la langue (affichage seulement)
    async def config_enable(self, interaction: Interaction, enabled: bool) -> None:
        """Active ou désactive la fonctionnalité sur le serveur
        
        :param enabled: True pour activer, False pour désactiver"""
        # Si on ne veut pas utiliser les docstrings, on peut aussi utiliser le paramètre description de app_commands (v. discord.py)
        if not isinstance(interaction.guild, discord.Guild):
            return await interaction.response.send_message(content="**Erreur ·** Cette commande n'est pas disponible en MP", ephemeral=True)
        
        self.set_enabled(interaction.guild, enabled)
        await interaction.response.send_message(content=f"**Succès ·** La fonctionnalité a été {'activée' if enabled else 'désactivée'} sur le serveur", ephemeral=True)
        
    @config_group.command(name='cooldown')
    async def config_cooldown(self, interaction: Interaction, cooldown: app_commands.Range[int, 0]) -> None:
        """Définit le cooldown entre chaque réponse
        
        :param cooldown: Le cooldown en secondes"""
        if not isinstance(interaction.guild, discord.Guild):
            return await interaction.response.send_message(content="**Erreur ·** Cette commande n'est pas disponible en MP", ephemeral=True)
        
        self.set_guild_cooldown(interaction.guild, cooldown)
        await interaction.response.send_message(content=f"**Succès ·** Le cooldown a été défini à {cooldown} secondes", ephemeral=True)
        
    # On crée un groupe de commandes pour gérer les messages de réponse (serveur uniquement, par défaut accessible à tout le monde)
    
    trig_group = app_commands.Group(name='trig', description="Gestion des messages de réponse du module d'exemple de triggers", guild_only=True)
    
    @trig_group.command(name='list')
    async def trig_list(self, interaction: Interaction) -> None:
        """Affiche la liste des messages de réponse"""
        if not isinstance(interaction.guild, discord.Guild):
            return await interaction.response.send_message(content="**Erreur ·** Cette commande n'est pas disponible en MP", ephemeral=True)
        
        messages = self.get_messages(interaction.guild)
        if not messages:
            return await interaction.response.send_message(content="**Erreur ·** Aucun message de réponse n'a été défini sur ce serveur", ephemeral=True)
        
        text = ''
        for message in messages:
            text += f"`{message['id']}` : *{message['trigger']}* -> *{message['response']}*\n"
            
        embed = discord.Embed(title="Messages de réponse", description=text)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @trig_group.command(name='add')
    @app_commands.rename(trigger='déclencheur', response='réponse')
    async def trig_add(self, interaction: Interaction, trigger: str, response: str) -> None:
        """Ajoute un message de réponse
        
        :param trigger: Le message qui déclenche la réponse
        :param response: La réponse à envoyer"""
        if not isinstance(interaction.guild, discord.Guild):
            return await interaction.response.send_message(content="**Erreur ·** Cette commande n'est pas disponible en MP", ephemeral=True)
        
        trigger = trigger.lower() # On met le trigger en minuscules pour éviter les problèmes de casse
        # On vériie que le trigger n'est pas déjà utilisé
        messages = self.get_messages(interaction.guild)
        for msg in messages:
            if msg['trigger'] == trigger:
                return await interaction.response.send_message(content="**Erreur ·** Ce déclencheur est déjà utilisé", ephemeral=True)
        # On veut pas plus de 20 triggers par serveur pour éviter les abus
        if len(messages) >= 20:
            return await interaction.response.send_message(content="**Erreur ·** Tu as atteint le nombre maximum de messages de réponse", ephemeral=True)
        
        self.add_message(interaction.guild, trigger, response, interaction.user.id)
        await interaction.response.send_message(content=f"**Succès ·** Le message de réponse a été ajouté", ephemeral=True)
        
    @trig_group.command(name='remove')
    async def trig_remove(self, interaction: Interaction, id: int) -> None:
        """Supprime un message de réponse
        
        :param id: L'ID du message à supprimer"""
        if not isinstance(interaction.guild, discord.Guild):
            return await interaction.response.send_message(content="**Erreur ·** Cette commande n'est pas disponible en MP", ephemeral=True)
        
        self.remove_message(interaction.guild, id)
        await interaction.response.send_message(content=f"**Succès ·** Le message de réponse a été supprimé", ephemeral=True)
        
    # Vu que ça va pas être facile de retrouver l'ID de tête, on va créer une fonction d'autocomplétion pour la commande trig remove
    @trig_remove.autocomplete('id')
    async def trig_remove_autocomplete(self, interaction: Interaction, current: str):
        # On se sert de fuzzy.finder qui est intégré dans le dossier common.utils pour retrouver le trigger le plus proche lié à l'ID
        if not isinstance(interaction.guild, discord.Guild):
            return [] # Si on est en MP, on renvoie une liste vide pour ne pas afficher de résultats
        messages = self.get_messages(interaction.guild)
        results = fuzzy.finder(current, messages, key=lambda x: x['trigger']) # La fonction les trie par similitude avec ce qui est tapé ('current')
        return [app_commands.Choice(name=f"{result['id']} : {result['trigger']}", value=result['id']) for result in results] # On renvoie une liste de choix pour l'autocomplétion (v. discord.py)

    # On crée un listener de message pour répondre aux messages de réponse
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not isinstance(message.guild, discord.Guild) or message.author.bot: # On s'assure que le message est bien sur un serveur et qu'il n'est pas envoyé par un bot
            return
        
        if not self.is_enabled(message.guild): # On vérifie que la fonctionnalité est activée sur le serveur
            return
        
        # On vérifie que le cooldown est bien passé
        guild_cooldown = self.get_guild_cooldown(message.guild)
        cds = self.__cooldowns.setdefault(message.guild.id, {})
        last_resp = cds.setdefault(message.author.id, 0)
        if last_resp + guild_cooldown > datetime.now().timestamp():
            return
        
        # On recherche un événement qui correspond au message (pas optimisé du tout mais c'est un exemple)
        messages = self.get_messages(message.guild)
        for msg in messages:
            if msg['trigger'] in message.content:
                await message.channel.send(msg['response'], silent=True) # On envoie la réponse en silent pour éviter que des malins s'en servent pour spam
                cds[message.author.id] = datetime.now().timestamp() # On met à jour le cooldown avec le timestamp actuel
                break # On sort de la boucle pour ne pas répondre plusieurs fois
        
async def setup(bot):
    await bot.add_cog(Example(bot))
