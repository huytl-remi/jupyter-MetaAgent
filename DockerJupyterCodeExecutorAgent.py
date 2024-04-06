from docker_jupyter_server import DockerJupyterServer
from jupyter_code_executor import JupyterCodeExecutor
from base_1 import CodeBlock, IPythonCodeResult
from markdown_code_extractor import MarkdownCodeExtractor
from typing import List, Optional, Union, Dict
from metagpt.roles import Role
from metagpt.schema import Message
from pathlib import Path
import logging
import re
import asyncio

logger = logging.getLogger(__name__)

class DockerJupyterAgent(Role):
    name: str = "DockerJupyterAgent"
    profile: str = "A Docker Jupyter agent that can create and execute code in a Jupyter notebook environment."

    def __init__(
        self,
        custom_image_name: Optional[str] = None,
        container_name: Optional[str] = None,
        auto_remove: bool = True,
        stop_container: bool = True,
        docker_env: Dict[str, str] = {},
        token: Union[str, DockerJupyterServer.GenerateToken] = DockerJupyterServer.GenerateToken(),
        kernel_name: str = "python3",
        timeout: int = 60,
        output_dir: Union[Path, str] = Path("."),
        **kwargs,
    ):
        super().__init__(**kwargs)
        
        try:
            self.docker_jupyter_server = DockerJupyterServer(
                custom_image_name=custom_image_name,
                container_name=container_name,
                auto_remove=auto_remove,
                stop_container=stop_container,
                docker_env=docker_env,
                token=token,
            )
            self.jupyter_code_executor = JupyterCodeExecutor(
                jupyter_server=self.docker_jupyter_server,
                kernel_name=kernel_name,
                timeout=timeout,
                output_dir=output_dir,
            )
            self.markdown_code_extractor = MarkdownCodeExtractor()
            self.set_actions([self.generate_code, self.execute_code])
            self._set_react_mode(react_mode="by_order")
        except Exception as e:
            logger.exception("Error initializing DockerJupyterAgent")
            raise e

    async def generate_code(self, instruction: str, language: str) -> str:
        try:
            prompt = f"""
            Write a {language} function that can {instruction}.
            Return ```{language} your_code_here ``` with NO other texts.
            Your code:
            """
            rsp = await self._aask(prompt)
            code_text = self._parse_code(rsp, language)
            return code_text
        except Exception as e:
            logger.exception(f"Error generating code for instruction: {instruction}")
            raise e

    async def execute_code(self, code_blocks: List[CodeBlock], language: str) -> IPythonCodeResult:
        if language not in self.jupyter_code_executors:
            raise ValueError(f"Unsupported language: {language}")
        return self.jupyter_code_executors[language].execute_code_blocks(code_blocks)

    async def _act(self) -> Message:
        logger.info(f"{self._setting}: to do {self.rc.todo}")
        todo = self.rc.todo

        if todo == self.generate_code:
            msg = self.get_memories(k=1)[0]
            code_blocks = self.markdown_code_extractor.extract_code_blocks([msg])
            if not code_blocks:
                raise ValueError("No code block found in the input message")
            language = code_blocks[0].language
            code_text = await todo(msg.content, language)
            msg = Message(content=code_text, role=self.profile, cause_by=type(todo))
        elif todo == self.execute_code:
            code_blocks = self.markdown_code_extractor.extract_code_blocks(self.get_memories())
            if not code_blocks:
                raise ValueError("No code block found in the input messages")
            language = code_blocks[0].language
            result = await todo(code_blocks, language)
            msg = Message(content=result.output, role=self.profile, cause_by=type(todo))

        self.rc.memory.add(msg)
        return msg

    async def run(self, msg: Message) -> Message:
        try:
            self.start_server()
            self._observe(msg)
            async for msg in self.react():
                self.rc.memory.add(msg)
                if not self._is_continue():
                    return msg
            raise ValueError(f"{self.name} stop for `{self.rc.reason}`")
        except Exception as e:
            logger.exception(f"{self.name} error")
            raise e
        finally:
            self.stop_server()

    def _parse_code(self, rsp: str, language: str) -> str:
        pattern = fr"```{language}(.*?)```"
        match = re.search(pattern, rsp, re.DOTALL)
        if match:
            code_text = match.group(1) if match else rsp
        else:
            logger.warning(f"No code block found in response: {rsp}. Returning full response as fallback.")
            code_text = rsp
        return code_text
        
    def start_server(self):
        try:
            self.docker_jupyter_server.start()
        except Exception as e:
            logger.exception("Error starting Docker Jupyter server")
            raise e
        
    def stop_server(self):
        try:
            self.docker_jupyter_server.stop()
        except Exception as e:
            logger.exception("Error stopping Docker Jupyter server")
            raise e
        
async def main():
    msg = "Write an advanced TypeScript code related to Solana blockchain framework and then write unit test for it and execute the testing phase to make sure everything is working"
    role = DockerJupyterAgent()
    logger.info(msg)
    result = await role.run(msg)
    logger.info(result)

asyncio.run(main)